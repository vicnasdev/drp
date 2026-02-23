#!/bin/bash
trap '' INT
cd /home/vic/Desktop/Code/Github/drp
git add -A
git commit -m "remove temp scripts"
git push
echo "DONE"
rm -f "$0"
