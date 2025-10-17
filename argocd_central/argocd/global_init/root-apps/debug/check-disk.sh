#!/bin/bash
set -e
NS="kube-system"
LBL="app=node-debug"
printf "%-50s %-10s %-10s %-10s %-20s\n" NODE USED AVAIL USE% MOUNT
kubectl get pods -n $NS -l $LBL -o custom-columns=P:.metadata.name,N:.spec.nodeName --no-headers | while read -r P N; do
  kubectl exec -n $NS "$P" -- chroot /hostdir sh -c "df -h | grep -vE '^Filesystem|tmpfs|overlay|shm'" | while read -r L; do
    printf "%-50s %-10s %-10s %-10s %-20s\n" "$N" $(awk '{print $3, $4, $5, $6}' <<< "$L")
  done
done
