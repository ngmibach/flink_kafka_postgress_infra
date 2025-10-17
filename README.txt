start up:
after docker compose up -d completed go to argocd_central run
bash init.sh (build custom image and init git repo)

get argocd password:
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

argocd https://localhost:30001
kubeopsview http://localhost:30002
appexample: http://localhost:30000

rebuild appexample to have different build by timestamp
go to folder app-example
bash build-image.sh

OR just run full_up.sh (^.^)