#!/bin/sh
# Crée (une seule fois) l'autorité de certification interne Aptitude, puis un certificat
# HTTPS pour le site, signé par elle. Let's Encrypt ne délivre pas de certificat pour
# un nom en .local : c'est cette autorité, installée sur les postes et les mobiles,
# qui rend le cadenas valide et permet d'installer l'application (PWA).
#
# Usage (depuis la racine du projet, sur le serveur) :
#   sh docker/certs/creer-certificat.sh support.aptitudes.local 10.10.1.77
#   sh docker/certs/creer-certificat.sh support.aptitudes.local 10.10.1.77 support.aptitudes.net
# Arguments : nom principal, adresse IP du serveur, puis noms supplémentaires (facultatifs).
#
# Produit dans ./certs (jamais versionné) :
#   ca/aptitude-ca.key        clé de l'autorité — À METTRE À L'ABRI, hors du serveur après usage
#   aptitude-ca.crt / .cer    certificat racine à installer sur les postes et mobiles (public)
#   support.crt / support.key certificat du site, lu par Traefik (docker/traefik/tls.yml)
#
# Relancer le script avant l'expiration (397 jours) renouvelle le certificat du site avec
# la même autorité : rien à réinstaller sur les appareils. Traefik le recharge à chaud.
set -eu

DOMAIN="${1:?Nom du site attendu, ex. support.aptitudes.local}"
IP="${2:?Adresse IP du serveur attendue, ex. 10.10.1.77}"
shift 2
EXTRA_NAMES="$*"

OUT="${CERTS_DIR:-./certs}"
CA_DIR="$OUT/ca"
CA_KEY="$CA_DIR/aptitude-ca.key"
CA_CRT="$OUT/aptitude-ca.crt"
CA_DAYS=3650
SITE_DAYS=397   # au-delà, iPhone et navigateurs refusent le certificat

umask 077
mkdir -p "$CA_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- 1. Autorité interne (créée une seule fois) ---------------------------------
if [ ! -f "$CA_KEY" ] && [ -f "$CA_CRT" ]; then
  # L'autorité existe déjà sur les appareils : en recréer une obligerait à tout réinstaller.
  echo "La clé de l'autorité ($CA_KEY) est absente alors que $CA_CRT existe." >&2
  echo "Remettez la clé mise à l'abri à cet emplacement, puis relancez le script." >&2
  exit 1
fi
if [ ! -f "$CA_KEY" ]; then
  echo "Création de l'autorité de certification interne Aptitude…"
  cat > "$WORK/ca.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3_ca
[dn]
O = Aptitude Services
CN = Aptitude Services - Autorite interne
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
# Limite l'autorité aux noms et adresses d'Aptitude : même si sa clé fuitait,
# elle ne pourrait pas servir à usurper un autre site sur les appareils qui lui font confiance.
nameConstraints = critical, permitted;DNS:aptitudes.local, permitted;DNS:aptitudes.net, permitted;IP:10.0.0.0/255.0.0.0, permitted;IP:172.16.0.0/255.240.0.0, permitted;IP:192.168.0.0/255.255.0.0
EOF
  openssl req -x509 -new -newkey rsa:4096 -sha256 -nodes -days "$CA_DAYS" \
    -keyout "$CA_KEY" -out "$CA_CRT" -config "$WORK/ca.cnf"
  chmod 600 "$CA_KEY"
else
  echo "Autorité existante réutilisée ($CA_KEY)."
fi
[ -f "$CA_CRT" ] || { echo "Certificat racine introuvable : $CA_CRT" >&2; exit 1; }
openssl x509 -in "$CA_CRT" -outform der -out "$OUT/aptitude-ca.cer"
chmod 644 "$CA_CRT" "$OUT/aptitude-ca.cer"

# --- 2. Certificat du site -------------------------------------------------------
SAN="DNS:$DOMAIN,IP:$IP"
for name in $EXTRA_NAMES; do SAN="$SAN,DNS:$name"; done

cat > "$WORK/site.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
[dn]
O = Aptitude Services
CN = $DOMAIN
[v3_site]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
subjectAltName = $SAN
EOF

openssl req -new -newkey rsa:2048 -sha256 -nodes \
  -keyout "$WORK/support.key" -out "$WORK/support.csr" -config "$WORK/site.cnf"
openssl x509 -req -in "$WORK/support.csr" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -CAserial "$CA_DIR/aptitude-ca.srl" -days "$SITE_DAYS" -sha256 \
  -extfile "$WORK/site.cnf" -extensions v3_site -out "$WORK/support.crt"

# Chaîne complète (site + autorité) : certains clients en ont besoin.
cat "$WORK/support.crt" "$CA_CRT" > "$OUT/support.crt"
mv "$WORK/support.key" "$OUT/support.key"
# Traefik tourne en root dans son conteneur : lecture seule suffit.
chmod 644 "$OUT/support.crt"
chmod 600 "$OUT/support.key"

openssl verify -CAfile "$CA_CRT" "$WORK/support.crt" >/dev/null
echo
echo "Certificat du site : $OUT/support.crt (valable $SITE_DAYS jours)"
openssl x509 -in "$WORK/support.crt" -noout -subject -enddate
echo "Noms couverts : $SAN"
echo
echo "À installer sur les postes et mobiles : $OUT/aptitude-ca.crt (ou .cer pour Windows)"
echo "Empreinte SHA-256 (à vérifier sur chaque appareil) :"
openssl x509 -in "$CA_CRT" -noout -fingerprint -sha256
echo
echo "Pensez à copier $CA_KEY hors du serveur (coffre, clé USB chiffrée), puis à le supprimer d'ici."
