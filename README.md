# Goodix 27c6:538d sous Linux

Compte rendu d'une tentative pour faire fonctionner le lecteur d'empreintes
Goodix `27c6:538d` d'un Dell Inspiron 3501 sous Ubuntu 26.04, sans Windows.

**Conclusion : le capteur communique, capture des images exploitables et
l'enregistrement fonctionne, mais aucun algorithme libre testé (NBIS, SIGFM)
ne reconnaît un doigt de façon fiable.** La surface vue par le capteur est trop
petite : 4 à 5 crêtes parallèles, qui se ressemblent d'un doigt à l'autre.
Pour un usage réel, un lecteur USB pris en charge par libfprint reste la seule
solution fiable.

## Sommaire

1. [Audit de `run_538d.py`](#1-audit-de-run_538dpy)
2. [Vérification en lecture seule](#2-vérification-en-lecture-seule)
3. [Pilote libfprint communautaire](#3-pilote-libfprint-communautaire)
4. [Corrections du pilote](#4-corrections-du-pilote)
5. [Reconnaissance avec NBIS](#5-reconnaissance-avec-nbis)
6. [Reconnaissance avec SIGFM](#6-reconnaissance-avec-sigfm)
7. [Reproduire](#7-reproduire)
8. [Contenu du dépôt](#8-contenu-du-dépôt)

## 1. Audit de `run_538d.py`

[`goodix-fp-dump`](https://github.com/goodix-fp-linux-dev/goodix-fp-dump)
fournit `run_538d.py`, qui reflashe le capteur avant de capturer des images.
Avant de le lancer en root, le script et tout le code appelé
(`driver_53xd.py`, `goodix.py`, `protocol.py`, `tool.py`) ont été audités.

**Comportement selon l'état du capteur :**

| Version du firmware | Clé PSK | Action |
|---|---|---|
| `GF5298_GM168SEC_APP_13016` | nulle | capture d'images, aucune écriture en flash |
| `GF5298_GM168SEC_APP_13016` | autre | **effacement de l'application** puis flash |
| `GF5298_GM168SEC_APP_130xx` (autre) | — | **effacement de l'application** puis flash |
| `MILAN_GM168SEC_IAP_10007` (bootloader) | — | écriture de la PSK, flash du firmware 13016 |
| autre | — | arrêt « Invalid firmware », rien n'est écrit |

**Commandes USB qui écrivent en flash :** `0xA4` (effacement de l'application),
`0xE0` (écriture de la PSK), `0xF0` (écriture du firmware, 95 blocs de 256
octets). Le bootloader n'est jamais réécrit, ce qui rend la plupart des
échecs rattrapables en relançant le script.

**Ce qui est installé :** le firmware `GF5298_GM168SEC_APP_13016.bin`
(24 268 octets) et une clé PSK de 32 octets nuls. Le script ne vérifie aucune
somme de contrôle du fichier, et la clé nulle étant publique, la liaison TLS
entre le PC et le capteur ne protège plus rien.

**Points de non-retour :**
1. L'effacement du firmware d'origine, sans sauvegarde préalable.
2. L'écrasement de la clé PSK d'origine, qui ne peut pas être lue avant.
3. Le flash du firmware 13016.

**Risques relevés :**
- L'effacement a lieu *avant* que le script voie la version du bootloader :
  si celle-ci diffère de `10007`, le capteur reste sans application.
- Un Ctrl+C pendant le flash n'est pas intercepté (`KeyboardInterrupt` n'hérite
  pas d'`Exception`) : ni effacement ni vérification ne suivent.
- Pendant la capture, `openssl s_server` écoute en root sur le port 4433,
  sur toutes les interfaces, avec la clé nulle.
- `fingerprint.pgm` est écrit en clair dans le répertoire courant.

## 2. Vérification en lecture seule

[`check_538d_ro.py`](check_538d_ro.py) réutilise `goodix.Device` sans le
modifier, mais remplace l'écriture USB par une liste blanche : seules
`0x00` (nop), `0xA8` (version), `0xE4` (lecture du hash de la PSK) et `0xA6`
(lecture de l'OTP) peuvent atteindre le capteur. Il affiche ce que ferait
`run_538d.py`.

Sur ce capteur, le firmware était déjà `GF5298_GM168SEC_APP_13016` avec la
clé nulle (hash `sha256(0^32)`) : il avait déjà été flashé avec cet outil, et
**aucun flash n'a été nécessaire** par la suite.

## 3. Pilote libfprint communautaire

Ni la libfprint d'Ubuntu, ni le pilote propriétaire Dell
`libfprint-2-tod1-goodix` ne prennent en charge `538d`. Le seul pilote
existant est `goodixtls53xd`, dans la branche `unstable` de
[infinytum/libfprint](https://github.com/infinytum/libfprint) (dernier commit
en novembre 2021, empaqueté sur Arch sous `libfprint-goodix-521d`). Il exige
exactement le firmware 13016 et la clé nulle, et n'écrit jamais en flash.

En l'état, il communique bien avec le capteur (vérifications, poignée de main
TLS, lecture des images) mais l'image produite est inexploitable.

## 4. Corrections du pilote

Branche `goodix53xd` du fork infinytum
([correctifs](patches/libfprint-infinytum)) :

| Problème | Correction |
|---|---|
| Les images d'un appui sont recollées comme pour un capteur à glissement (résultat de 36 ou −711 pixels de haut) | moyenne de 3 images du même appui |
| Pas de soustraction de l'image à vide (code désactivé et faux) | image sans doigt capturée au début de chaque scan, puis soustraite |
| Bandes horizontales, bord aux valeurs extrêmes | moyenne de chaque ligne retirée, bord de 2 pixels rogné, contraste étiré entre les 2e et 98e centiles ; image finale 60×76 |
| Registre `0x022c` reçoit `05 00` au lieu de `05 03` (initialiseur `guint16` entre accolades) | valeur `0x0305` |
| Détection matérielle du doigt (FDT) qui se déclenche sans doigt : ses seuils viennent du capteur de l'auteur | détection par l'image : une capture toutes les 100 ms comparée à l'image à vide (écart ~0 sans doigt, ~1500 à 1900 avec) |
| Commande FDT mode avec les octets de calibration de l'auteur | octets lus dans l'OTP du capteur |
| `double free` à la fermeture : le scan suivant démarrait avant la fin du précédent, puis perdait sa référence | fin de la machine à états avant de signaler le retrait du doigt |
| Compilation impossible avec GCC 14 | `-Wno-incompatible-pointer-types`, comme le paquet AUR |

Une variable `GOODIX53XD_DUMP_DIR` permet d'enregistrer chaque image produite
pour le débogage.

## 5. Reconnaissance avec NBIS

NBIS est l'algorithme par défaut de libfprint : il compare des minuties
(fins et bifurcations de crêtes) avec bozorth3, seuil 24.

- Enregistrement : 5 appuis acceptés sur 9, les autres sans minutie trouvée.
- Empreinte stockée : **1 à 2 minuties par image**, 7 au total.
- Vérification : 4 appuis sur 5 rejetés faute de minuties, le dernier avec un
  score de 0/24.

Bozorth3 a besoin d'une dizaine de minuties communes. Baisser le seuil ne
servirait à rien : avec 1 ou 2 points, n'importe quel doigt finirait accepté.

## 6. Reconnaissance avec SIGFM

SIGFM compare des points SIFT (OpenCV) plutôt que des minuties ; il a été écrit
par la communauté Goodix pour les petits capteurs. Il vit dans la branche
`sigfm` de [goodix-fp-linux-dev/libfprint](https://github.com/goodix-fp-linux-dev/libfprint),
qui ne contient aucun pilote goodixtls. Le pilote corrigé y a été transplanté
(branche `goodix53xd`, [correctifs](patches/libfprint-sigfm)), avec une
correction de SIGFM lui-même : `fp_print_serialize` libérait un `GPtrArray`
avec `g_clear_object`, si bien que l'empreinte enregistrée n'était pas
sauvegardée.

- Enregistrement : 5 appuis acceptés sur 5.
- Vérification en conditions réelles : 1 appui de l'index reconnu sur 6,
  4 appuis du majeur refusés sur 4.

Banc de test hors ligne ([`tools/sigfm_bench.cpp`](tools/sigfm_bench.cpp)) sur
21 images : 5 images de l'index comme référence, 10 autres images de l'index
et 6 du majeur comparées à elles.

| Taille de l'image | Index reconnu | Majeur accepté à tort |
|---|---|---|
| 60×76 | 0/10 | 0/6 |
| agrandie ×2 | 5/10 | 1/6 |
| agrandie ×3 | 9/10 | 5/6 |

Aucun seuil ne sépare les deux doigts : à ×2, une image du majeur obtient
2954, plus que la meilleure image de l'index (540). Les images de l'index et du
majeur montrent les mêmes crêtes parallèles ; à cette échelle, un doigt
ressemble à n'importe quel autre.

## 7. Reproduire

Dépendances (Ubuntu 26.04) : `meson`, `ninja-build`, `gcc`, `libglib2.0-dev`,
`libgusb-dev`, `libssl-dev`, et pour SIGFM `libopencv-dev` et `doctest-dev`.

```sh
git clone -b goodix53xd-sigfm https://github.com/BaptistePignier/libfprint.git
cd libfprint
meson setup build -Ddrivers=goodixtls53xd -Dintrospection=false -Ddoc=false \
    -Dgtk-examples=false -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C build
sudo build/examples/img-capture capture.pgm   # une capture
sudo build/examples/enroll                    # enregistrement
sudo build/examples/verify                    # vérification
```

Les exemples utilisent la bibliothèque compilée, sans toucher à la libfprint
du système. Pour la branche sans SIGFM, remplacer `goodix53xd-sigfm` par
`goodix53xd-infinytum` (pas besoin d'OpenCV).

Au lancement : valider sans toucher le capteur (image à vide), attendre
2 secondes, puis poser le doigt environ 1 seconde. Le programme `enroll` active
tous les messages de debug ; `G_MESSAGES_DEBUG=` les coupe.

Vérification en lecture seule de l'état du capteur :

```sh
git clone https://github.com/goodix-fp-linux-dev/goodix-fp-dump.git
python3 -m venv .venv && .venv/bin/pip install pyusb python-periphery spidev
sudo .venv/bin/python check_538d_ro.py
```

## 8. Contenu du dépôt

| Chemin | Rôle |
|---|---|
| `check_538d_ro.py` | état du capteur en lecture seule, à côté d'un clone de `goodix-fp-dump` |
| `patches/libfprint-infinytum/` | correctifs sur `infinytum/libfprint` (`unstable`) |
| `patches/libfprint-sigfm/` | correctifs sur `goodix-fp-linux-dev/libfprint` (`sigfm`) |
| `tools/sigfm_bench.cpp` | banc de test SIGFM hors ligne sur des images extraites |

Les deux branches sont aussi publiées dans
[BaptistePignier/libfprint](https://github.com/BaptistePignier/libfprint) :
`goodix53xd-infinytum` et `goodix53xd-sigfm`.

Aucune donnée biométrique n'est incluse. libfprint est sous LGPL 2.1,
goodix-fp-dump sous licence MIT ; le firmware Goodix n'est pas redistribué ici.
