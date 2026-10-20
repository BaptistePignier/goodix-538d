#!/bin/sh
# Installs fprintd + libfprint (SIGFM, template learning) for the Goodix
# 27c6:538d in /opt/fprint-538d, and makes systemd start it instead of
# Ubuntu's fprintd. Ubuntu's packages are left untouched.
set -eu

STAGE="$1"
DROPIN_DIR=/etc/systemd/system/fprintd.service.d
DROPIN="$DROPIN_DIR/goodix-538d.conf"

# 1. Our libfprint and fprintd, owned by root
rm -rf /opt/fprint-538d
cp -r "$STAGE/opt/fprint-538d" /opt/fprint-538d
chown -R root:root /opt/fprint-538d
chmod -R go-w /opt/fprint-538d

# 2. systemd override: our fprintd instead of /usr/libexec/fprintd
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN" <<'EOF'
# Goodix 27c6:538d: fprintd and libfprint with SIGFM and template learning,
# see https://github.com/BaptistePignier/goodix-538d
# To use Ubuntu's fprintd again: remove this file, then
#   systemctl daemon-reload && systemctl restart fprintd
[Service]
ExecStart=
ExecStart=/opt/fprint-538d/libexec/fprintd
EOF

# 3. Keep the OpenCV runtime libraries used by libfprint if the development
#    packages that pulled them in are removed
apt-mark manual libopencv-core410 libopencv-features2d410 \
    libopencv-flann410 libopencv-imgproc410

systemctl daemon-reload
systemctl restart fprintd
