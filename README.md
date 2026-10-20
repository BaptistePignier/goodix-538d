# Goodix 27c6:538d sous Linux

Compte rendu d'une tentative pour faire fonctionner le lecteur d'empreintes
Goodix `27c6:538d` d'un Dell Inspiron 3501 sous Ubuntu 26.04, sans Windows.

**Conclusion.** Le pilote libfprint corrigé ici communique de façon stable
avec le capteur, le calibre correctement, détecte le doigt et capture des
images nettes. Avec **l'apprentissage de l'empreinte** (section 9), comme le
moteur Goodix de Windows, **84 à 85 % des appuis naturels sont reconnus**
après une vingtaine d'utilisations, et **aucun doigt étranger n'a été
accepté** (0 sur 40 appuis réels, 0 sur 80 hors ligne). Ces mesures viennent
de séances de quelques heures : seul un usage sur plusieurs jours dira si
elles tiennent.

Sans apprentissage, seuls 25 à 35 % des appuis étaient reconnus. Le capteur
ne voit que 4 ou 5 crêtes presque parallèles : sur un tel motif, la position
d'une image par rapport à une autre est indéterminée (le « problème
d'ouverture » du recalage d'images). Toutes les méthodes de comparaison
essayées butent sur ce plafond ; c'est l'accumulation d'images au fil des
utilisations qui le contourne.

## Sommaire

1. [Audit de `run_538d.py`](#1-audit-de-run_538dpy)
2. [Vérification en lecture seule](#2-vérification-en-lecture-seule)
3. [Pilote libfprint communautaire](#3-pilote-libfprint-communautaire)
4. [Premières corrections du pilote](#4-premières-corrections-du-pilote)
5. [NBIS puis SIGFM](#5-nbis-puis-sigfm)
6. [Calibration du capteur](#6-calibration-du-capteur)
7. [Captures, robustesse et enregistrement](#7-captures-robustesse-et-enregistrement)
8. [Comparaison des empreintes](#8-comparaison-des-empreintes)
9. [Apprentissage de l'empreinte](#9-apprentissage-de-lempreinte)
10. [Résultats](#10-résultats)
11. [Reproduire](#11-reproduire)
12. [Contenu du dépôt](#12-contenu-du-dépôt)

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

## 9. Apprentissage de l'empreinte

Les journaux du pilote Windows capturés par la communauté
([`goodix-fp-dump/log/ENGINE.log`](https://github.com/goodix-fp-linux-dev/goodix-fp-dump/tree/master/log),
moteur Goodix « Milan », capteur 5110 de même résolution) montrent comment
Windows s'en sort :

| Moteur Goodix (Windows) | Ce dépôt |
|---|---|
| Empreinte de 50 images au plus (`maxTempNum:50`) | 50 images |
| Chaque reconnaissance réussie ajoute l'image à l'empreinte (`gx_templateStudy`) | idem, `fpi_print_sigfm_learn()` |
| Seuils de qualité (25) et de couverture (65 %) | nouvel essai demandé pour les images peu distinctives |
| Calibration du gain et du décalage par pixel (`kr[]`, `b[]`) | décalage seulement |

**Apprentissage.** Quand une vérification réussit, l'image rejoint
l'empreinte ; au-delà de 50 images, la plus ancienne image apprise est
remplacée, les 20 images d'enregistrement restent. L'appelant enregistre
l'empreinte enrichie (l'exemple `verify` le fait ; fprintd doit être modifié).

**Nouvel essai plutôt qu'échec.** Les appuis ratés ne sont pas des images
floues mais des crêtes parallèles très régulières : moins de points SIFT,
signal plus fort et plus cohérent ([`tools/quality.py`](tools/quality.py)).
Le pilote demande de reposer le doigt quand une image a moins de 33 points
SIFT, ou, en vérification, quand son signal dépasse 230. Une demande de
nouvel appui ne consomme pas d'essai dans fprintd.

## 10. Résultats

Cinq séries d'appuis ont été collectées
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

**Apprentissage, simulation hors ligne**
([`tools/learning.py`](tools/learning.py) : 20 images d'enregistrement,
60 appuis naturels rejoués dans l'ordre, 40 appuis d'autres doigts) :

| | Sans apprentissage | Avec apprentissage |
|---|---|---|
| Appuis reconnus | 28 % | 63 % |
| Déverrouillage en 3 essais au plus | — | 90 % |
| Doigts étrangers, meilleur score (seuil 10) | 1 | 1 |

Les demandes de nouvel essai transforment 12 des 22 échecs en « repose ton
doigt » en ne redemandant qu'un appui reconnu sur 38 : 77 % des appuis
auxquels le pilote répond sont reconnus.

**Apprentissage, conditions réelles** (`enroll` puis `verify` en boucle) :

| Série | Index droit reconnu | Autres doigts acceptés |
|---|---|---|
| Juste après l'enregistrement | 34/40 (85 %) : 5/10, 9/10, 10/10, 10/10 | 0/30 |
| Une heure plus tard, avec les nouveaux essais | 26/31 (84 %), 2 nouveaux essais | 0/10 |

Pour aller plus loin : un usage sur plusieurs jours, la calibration du gain
par pixel, ou l'observation du pilote Windows (journaux et échanges USB
dans une machine virtuelle) pour connaître ses réglages de capture.

## 11. Reproduire

Dépendances (Ubuntu 26.04) : `meson`, `ninja-build`, `gcc`, `libglib2.0-dev`,
`libgusb-dev`, `libssl-dev`, `libopencv-dev`, `doctest-dev`.

```sh
git clone -b goodix53xd-sigfm https://github.com/BaptistePignier/libfprint.git
cd libfprint
meson setup build -Ddrivers=goodixtls53xd -Dintrospection=false -Ddoc=false \
    -Dgtk-examples=false -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C build
sudo G_MESSAGES_DEBUG=none build/examples/enroll   # 20 appuis
(echo 6; yes) | sudo G_MESSAGES_DEBUG=none build/examples/verify 2>&1 | grep -E "MATCH!|retry error"
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

## 12. Contenu du dépôt

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
| `tools/learning.py` | simulation de l'apprentissage de l'empreinte |
| `tools/quality.py` | indicateurs de qualité des appuis ratés |
| `tools/sigfm_bench.cpp` | premier banc de test SIGFM |

Les deux branches du pilote sont publiées dans
[BaptistePignier/libfprint](https://github.com/BaptistePignier/libfprint) :
`goodix53xd-infinytum` (section 4) et `goodix53xd-sigfm` (sections 5 à 9).

Aucune donnée biométrique n'est incluse. libfprint est sous LGPL 2.1,
goodix-fp-dump sous licence MIT ; le firmware Goodix n'est pas redistribué ici.
