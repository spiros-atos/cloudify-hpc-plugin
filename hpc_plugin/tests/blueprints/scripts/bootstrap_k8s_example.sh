#!/bin/bash -l

FILE="touch.script"

cat > $FILE <<- EOM
#!/bin/bash -l

cd /home/linux/ATOSES_spiros/monitoring_jobs/cfy_launch
ID=K8S_BB
cfy blueprints upload -b \$ID job.yaml
cfy deployments create -b \$ID
cfy executions start -d \$ID install


#touch test_$1.test

EOM
