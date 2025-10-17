#!/bin/bash
docker compose up -d

cd argocd_central
bash init.sh