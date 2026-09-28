#!/usr/bin/env bash
# Liste les processus du launcher et des modeles
ps -eo pid,etime,args | grep -E 'laya-serve|launcher\.py|ninfer-serve|start-ninfer' | grep -v grep || echo "aucun"
