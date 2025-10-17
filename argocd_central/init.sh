#!/bin/bash
(
    cd docker_build
    docker compose build
    docker compose push
)
rm -rf .git
git config --global user.email "you@example.com"
git config --global user.name "Your Name"
git init
git remote add origin http://localhost:3000/git/argocd_central.git
git add *
git commit -m "init"
git push origin master --force