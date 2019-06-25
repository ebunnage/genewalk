# GeneWalk

Optional: it is recommended to use Python virtual environments when installing
GeneWalk. You can start a new environment before installation by running in a terminal:
```
virtualenv genewalkenv --system-site-packages
source genewalkenv/bin/activate
```

### Install GeneWalk
To install the latest release of GeneWalk (preferred):
```
pip install genewalk
```
To install the latest code from Github (typically ahead of releases):
```
pip install git+https://github.com/churchmanlab/genewalk
```

### Set output directory
```
outDir=~/genewalk  
mkdir -p ${outDir}
```  

### Run GeneWalk
with the Pathway Commons data source (currently default):  
```
python get_node_vectors.py --path ${outDir}   
python get_null_distributions.py --path ${outDir}   
python perform_statistics.py --path ${outDir} 
```

### Optional: GeneWalk with INDRA data source
to use INDRA's sources to collect information and assemble a network, do
```
pip install indra  

python get_indra_stmts.py
python get_node_vectors.py --path ${outDir}
python get_null_distributions.py --path ${outDir}
python perform_statistics.py --path ${outDir}
```
