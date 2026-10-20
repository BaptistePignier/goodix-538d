# Goodix 27c6:538d sous Linux

Compte rendu d'une tentative pour faire fonctionner le lecteur d'empreintes
Goodix `27c6:538d` d'un Dell Inspiron 3501 sous Ubuntu 26.04, sans Windows.

**Conclusion.** Le pilote libfprint corrigé ici communique de façon stable
avec le capteur, le calibre correctement, détecte le doigt, capture des images
nettes et enregistre une empreinte. **Aucun doigt étranger n'a été accepté**
sur 40 appuis testés depuis la calibration. En revanche, seuls **25 à 35 % des appuis naturels du
bon doigt sont reconnus** : ce n'est pas utilisable au quotidien.

La limite vient de l'information contenue dans chaque image : le capteur ne
voit que 4 ou 5 crêtes presque parallèles. Sur un tel motif, la position
d'une image par rapport à une autre est indéterminée (le « problème
d'ouverture » du recalage d'images). Toutes les méthodes essayées
(minuties, points SIFT, corrélation, RANSAC, mosaïque) butent sur ce plafond.

Pour un usage réel, un lecteur USB pris en charge par libfprint reste la
seule solution fiable.

## Sommaire

1. [Audit de `run_538d.py`](#1-audit-de-run_538dpy)
2. [Vérification en lecture seule](#2-vérification-en-lecture-seule)
3. [Pilote libfprint communautaire](#3-pilote-libfprint-communautaire)
4. [Premières corrections du pilote](#4-premières-corrections-du-pilote)
5. [NBIS puis SIGFM](#5-nbis-puis-sigfm)
6. [Calibration du capteur](#6-calibration-du-capteur)
7. [Captures, robustesse et enregistrement](#7-captures-robustesse-et-enregistrement)
8. [Comparaison des empreintes](#8-comparaison-des-empreintes)
9. [Résultats](#9-résultats)
10. [Reproduire](#10-reproduire)
11. [Contenu du dépôt](#11-contenu-du-dépôt)

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

## 4. Premières corrections du pilote

Branche `goodix53xd-infinytum`
([correctifs](patches/libfprint-infinytum)) :

| Problème | Correction |
|---|---|
| Les images d'un appui sont recollées comme pour un capteur à glissement | moyenne de 3 images du même appui |
| Pas de soustraction de l'image à vide (code désactivé et faux) | image sans doigt capturée au début de chaque scan |
| Bandes horizontales, bord aux valeurs extrêmes | moyenne de chaque ligne retirée, bord de 2 pixels rogné, contraste étiré entre les 2e et 98e centiles ; image finale 60×76 |
| Registre `0x022c` reçoit `05 00` au lieu de `05 03` | valeur `0x0305` |
| Détection matérielle du doigt (FDT) qui se déclenche sans doigt : ses seuils viennent du capteur de l'auteur | détection par l'image, comparée à l'image à vide toutes les 100 ms |
| `double free` à la fermeture | fin de la machine à états avant de signaler le retrait du doigt |
| Compilation impossible avec GCC 14 | `-Wno-incompatible-pointer-types` |

Cette branche ne contient pas la calibration de la section 6 ; la suite du
travail est dans `goodix53xd-sigfm`.

## 5. NBIS puis SIGFM

**NBIS**, l'algorithme par défaut de libfprint, compare des minuties (fins et
bifurcations de crêtes) avec bozorth3. Il n'en trouve que **1 ou 2 par image** :
aucune vérification n'aboutit (score 0/24).

**SIGFM** compare des points SIFT (OpenCV) ; il a été écrit par la communauté
Goodix pour les petits capteurs. Il vit dans la branche `sigfm` de
[goodix-fp-linux-dev/libfprint](https://github.com/goodix-fp-linux-dev/libfprint),
qui ne contient aucun pilote goodixtls : le pilote y a été transplanté
(branche `goodix53xd-sigfm`, [correctifs](patches/libfprint-sigfm)).

Deux bugs de SIGFM lui-même ont été corrigés :
- `fp_print_serialize` libérait un `GPtrArray` avec `g_clear_object` :
  l'empreinte enregistrée n'était pas sauvegardée.
- `match::operator<` ne compare que `p1.y` (sa seconde condition ne peut
  jamais être vraie), donc le `std::set` des correspondances n'en garde
  **qu'une par ligne de l'image** et jette la plupart des bonnes.

Avec les images de la section 4, SIGFM acceptait des doigts étrangers dès que
l'image était agrandie : un majeur obtenait 2954 contre l'index, plus que
n'importe quelle paire du bon doigt. La cause est expliquée ci-dessous.

## 6. Calibration du capteur

Les données brutes (images 12 bits enregistrées par le pilote) ont montré que
**l'image à vide était saturée à 100 %** : tous les pixels à 4095. La
« soustraction de l'image à vide » retirait donc une constante, et le motif
fixe du capteur (différences de sensibilité, surtout par colonne) restait
dans chaque image. D'un doigt à l'autre, les images étaient corrélées à 0,32
en moyenne ; SIGFM appariait ce motif commun.

Les valeurs de DAC (décalage du signal envoyé avec chaque lecture d'image,
tirées de l'OTP) placent le capteur sans doigt au-dessus de 4095. Un balayage
sans doigt ([`goodix53xd_dacsweep`](tools/goodix53xd_dacsweep.c)) donne :

| Décalage du DAC | Niveau à vide (médiane) | Saturation |
|---|---|---|
| 0 (OTP) | 4095 | 100 % |
| +20 | 3771 | 0 % |
| +40 | 2321 | 0 % |
| +60 | 856 | 0 % |
| +80 | 0 | 100 % à 0 |

La réponse est **linéaire et identique pour tous les pixels** : −72,9 par pas
(72,2 à 73,4 selon le pixel), sans zones. Le pilote :
- capture deux images sans doigt, à +20 et +40 ;
- en **extrapole l'image à vide au décalage du doigt** (0), pixel par pixel :
  `2 × calib(+20) − calib(+40)` ;
- détecte le doigt à +20, par rapport à l'image à vide correspondante ;
- capture le doigt au décalage 0 (signal centré vers 2000) et y soustrait la
  vraie image à vide.

Résultat : plus de saturation, motif fixe nettement réduit, et **plus aucun
doigt étranger accepté** (voir section 9).

## 7. Captures, robustesse et enregistrement

| Problème | Correction |
|---|---|
| Image capturée pendant que le doigt se pose (contact partiel, flou) | attente que l'écart à l'image à vide se stabilise (moins de 5 % de variation) |
| Appuis trop légers | refus et nouvel essai demandé en dessous d'un écart de 1900 |
| Une image ne couvre qu'une petite partie du doigt | 20 images à l'enregistrement |
| Doigt encore posé pendant la calibration : il devient l'image à vide, le retrait passe pour un appui | vérification de la calibration (médiane à +20 au-dessus de 2500, moins de 5 % de pixels à 0 à +40), sinon nouvel essai |
| « Device disabled to prevent overheating » : le modèle de température simulé de libfprint s'épuise avec la détection par l'image | modèle désactivé, comme pour le pilote goodixmoc |
| Le lecteur se met en veille USB après 2 s (hwdb `60-autosuspend-libfprint-2`) et la première commande au réveil est perdue | jusqu'à 3 tentatives d'activation |
| Données laissées par un programme interrompu | lecture jusqu'à expiration à l'ouverture, comme `empty_buffer()` de goodix-fp-dump |
| Erreur TLS à l'activation jamais signalée (blocage) | erreur transmise à libfprint |

Variables d'environnement de mise au point : `GOODIX53XD_DUMP_DIR` (images
brutes, calibration, image finale et écart de contact de chaque appui),
`GOODIX53XD_DAC_OFFSET`, `GOODIX53XD_MIN_CONTACT`.

## 8. Comparaison des empreintes

Toutes les variantes ont été évaluées hors ligne sur les mêmes images, avec
les outils de [`tools/`](tools) :

| Méthode | Résultat |
|---|---|
| SIGFM d'origine | aucun doigt étranger, mais peu de bons appuis reconnus |
| SIGFM corrigé, ratio 0,8 (au lieu de 0,75), seuil 10 | retenu : doigts étrangers à 3 au plus, quelques points gagnés |
| Images agrandies ×2 ou ×3 | plus de points SIFT, mais aucun gain une fois le motif fixe retiré |
| Filtres d'image (passe-bande, CLAHE, motif fixe estimé) | pas de gain |
| Corrélation pixel à pixel avec recherche de rotation et translation | pire : un doigt étranger atteint 0,62, comme de vrais appuis |
| SIFT + RANSAC (rotation et translation, nombre de points cohérents) | 25 à 35 % comme SIGFM, mais marge face aux doigts étrangers de 1 ou 2 points seulement : non retenu |
| Mosaïque : assembler les images d'enregistrement | impossible : deux appuis consécutifs, à peine décalés, ne se recalent pas (corrélation 0,20 contre 0,15 entre doigts différents) |

## 9. Résultats

Trois séries d'appuis ont été collectées
([`goodix53xd_collect`](tools/goodix53xd_collect.c)), puis effacées après
l'analyse.

**Avant et après calibration** (30 appuis variés de l'index, 25 d'autres
doigts ; les 15 premiers appuis de l'index servent de référence) :

| | Sans calibration | Avec calibration |
|---|---|---|
| Doigt étranger, meilleur score (images ×2) | 4504 | 3 |
| Pixels saturés dans les images du doigt | 2,7 % | 0 % |

**Reconnaissance selon le nombre d'images de référence** (SIGFM corrigé,
seuil 10, appuis variés, 300 tirages) : 45 % avec 15 images, 59 % avec 25.

**Conditions réelles** (`enroll` et `verify` de libfprint, 20 images
d'enregistrement) : 3 appuis reconnus sur 9.

**Scénario réaliste hors ligne** (30 images d'enregistrement en décalant
peu à peu le doigt, 20 appuis naturels à vérifier, 40 appuis d'autres
doigts) :

| Méthode | Seuil | Doigts étrangers (max) | Appuis naturels reconnus |
|---|---|---|---|
| SIGFM corrigé | 10 | 0 | 25 % |
| SIFT + RANSAC | 6 | 4 | 25 % |
| SIFT + RANSAC | 5 | 4 | 35 % |

Pour aller plus loin, il faudrait observer le pilote Windows (échanges USB
dans une machine virtuelle) pour connaître ses réglages de capture ; son
algorithme de comparaison reste propriétaire.

## 10. Reproduire

Dépendances (Ubuntu 26.04) : `meson`, `ninja-build`, `gcc`, `libglib2.0-dev`,
`libgusb-dev`, `libssl-dev`, `libopencv-dev`, `doctest-dev`.

```sh
git clone -b goodix53xd-sigfm https://github.com/BaptistePignier/libfprint.git
cd libfprint
meson setup build -Ddrivers=goodixtls53xd -Dintrospection=false -Ddoc=false \
    -Dgtk-examples=false -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C build
sudo G_MESSAGES_DEBUG=none build/examples/enroll   # 20 appuis
sudo G_MESSAGES_DEBUG=none build/examples/verify
```

Les exemples utilisent la bibliothèque compilée, sans toucher à la libfprint
du système. Lever franchement le doigt entre deux appuis : le pilote attend
que le capteur soit vide pour se calibrer.

Collecte d'appuis pour l'analyse hors ligne (compiler l'outil comme indiqué
en tête de [`goodix53xd_collect.c`](tools/goodix53xd_collect.c)) :

```sh
sudo tools/goodix53xd_collect dataset index:30 majeur:15 annulaire:10
.venv/bin/python tools/analyze.py dataset work
```

Vérification en lecture seule de l'état du capteur :

```sh
git clone https://github.com/goodix-fp-linux-dev/goodix-fp-dump.git
python3 -m venv .venv && .venv/bin/pip install pyusb python-periphery spidev
sudo .venv/bin/python check_538d_ro.py
```

## 11. Contenu du dépôt

| Chemin | Rôle |
|---|---|
| `check_538d_ro.py` | état du capteur en lecture seule, à côté d'un clone de `goodix-fp-dump` |
| `patches/libfprint-infinytum/` | premières corrections sur `infinytum/libfprint` (`unstable`) |
| `patches/libfprint-sigfm/` | pilote complet et corrections de SIGFM sur `goodix-fp-linux-dev/libfprint` (`sigfm`) |
| `tools/goodix53xd_collect.c` | collecte guidée d'appuis, doigt par doigt |
| `tools/goodix53xd_dacsweep.c` | images sans doigt pour plusieurs décalages du DAC |
| `tools/analyze.py`, `tools/sigfm_matrix.cpp` | variantes de traitement d'image évaluées avec libsigfm |
| `tools/sigfm_tune.cpp`, `tools/tune.py` | SIGFM aux paramètres réglables, et balayage |
| `tools/correlation.py`, `tools/ransac.py` | prototypes de comparaison par corrélation et par SIFT + RANSAC |
| `tools/sigfm_bench.cpp` | premier banc de test SIGFM |

Les deux branches du pilote sont publiées dans
[BaptistePignier/libfprint](https://github.com/BaptistePignier/libfprint) :
`goodix53xd-infinytum` (section 4) et `goodix53xd-sigfm` (sections 5 à 7).

Aucune donnée biométrique n'est incluse. libfprint est sous LGPL 2.1,
goodix-fp-dump sous licence MIT ; le firmware Goodix n'est pas redistribué ici.
