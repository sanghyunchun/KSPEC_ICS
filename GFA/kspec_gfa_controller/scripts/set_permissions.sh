#!/bin/bash

# 설치 후 권한 설정
sudo mkdir -p /opt/kspec_gfa_controller/Image
sudo chown -R $(whoami):$(whoami) /opt/kspec_gfa_controller

echo "Permissions for /opt/kspec_gfa_controller set successfully."
