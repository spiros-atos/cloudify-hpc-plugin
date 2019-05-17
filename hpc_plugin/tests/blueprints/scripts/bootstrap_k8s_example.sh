#!/bin/bash -l

FILE="touch.script"

cat > $FILE <<- EOM
#!/bin/bash -l

cd /home/linux/ATOSES_spiros/monitoring_jobs/cfy_launch
ID=K8S_BB
cfy profiles use 10.244.2.44 #-u admin -p admin -t default_tenant
cfy blueprints upload -b \$ID job.yaml
cfy deployments create -b \$ID
cfy executions start -d \$ID install


#touch test_$1.test

EOM
