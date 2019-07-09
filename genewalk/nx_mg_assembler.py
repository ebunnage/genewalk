import re
import os
import pickle
import logging
import itertools
import pandas as pd
import networkx as nx
from indra.databases import hgnc_client
from goatools.obo_parser import GODag
from genewalk.resources import get_go_obo, get_goa_gaf, get_pc
from genewalk.get_indra_stmts import load_genes

logger = logging.getLogger('genewalk.nx_mg_assembler')


# TODO: these assemblers have a lot of code duplications, they could be
# refactored to derive from a single assembler class

def load_network(network_type, network_file, genes):
    if network_type == 'PC':
        MG = Nx_MG_Assembler_PC(genes)
        logger.info('Adding gene nodes from Pathway Commons.')
        MG.MG_from_PC()
        logger.info('Number of PC originating nodes %d' %
                    nx.number_of_nodes(MG.graph))
        logger.info('Adding GO nodes.')
        MG.add_GOannotations()
        MG.add_GOontology()
    elif network_type == 'INDRA':
        logger.info('Loading %s' % network_file)
        with open(network_file, 'rb') as f:
            stmts = pickle.load(f)

        MG = Nx_MG_Assembler_INDRA(stmts)
        del stmts

        logger.info('Adding nodes from INDRA stmts.')
        MG.MG_from_INDRA()

        # TODO: implement generic FamPlex construction for statements
        ffplx = 'INDRA_fplx.txt'
        MG.add_FPLXannotations(os.path.join(args.path, ffplx))

        logger.info('Number of INDRA originating nodes %d.' %
                    nx.number_of_nodes(MG.graph))

        logger.info('Adding GO nodes.')
        MG.add_GOannotations()
        MG.add_GOontology()
    elif network_type == 'user':
        logger.info('Loading user-provided GeneWalk Network from %s.' %
                    network_file)
        MG = Nx_MG_Assembler_fromUser(network_file)
    else:
        raise ValueError('Unknown network_type: %s' % network_type)
    return MG


class Nx_MG_Assembler_PC(object):
    """The Nx_MG_Assembler_PC assembles a GeneWalk Network with gene reactions
    from Pathway Commons and GO ontology and annotations into a networkx
    (undirected)  MultiGraph including edge attributes.

    Parameters
    ----------
    fgenes : str
        path to text file with input list (without header) containing
        genes of interest. For human genes (default), use HGNC identifiers
        (preferred, eg HGNC:7553) or current human HGNC gene symbols (eg MYC).
        In case of mouse genes use MGD identifiers (eg MGI:97250).
    mouse_genes : Optional[bool]
        Set to True in case the gene list contains mouse genes. Default: False
    
    Attributes
    ----------
    graph : networkx.MultiGraph
        A GeneWalk Network that is assembled by this assembler.
    GOA : pandas.DataFrame
        GO annotation in pd.dataframe format
    OGO : goatools.GODag
        GO ontology, GODag object (see goatools) 
    """
    def __init__(self,fgenes,mouse_genes=False):
        self.mouse_genes=mouse_genes
        self.hgenes=self._get_hgenes(fgenes)  # dataframe with columns:
        # gene symbols ('Symbol'), HGNC ids ('HGNC') and uniprot IDs ('UP').
        self.graph = nx.MultiGraph()
        self.PC = []
        self.GOA = []
        self.OGO = []
        self.EC_GOA = ['EXP', 'IDA', 'IPI', 'IMP', 'IGI', 'IEP', 'HTP', 'HDA',
                       'HMP', 'HGI', 'HEP', 'IBA', 'IBD']
    
    def _get_hgenes(self, fname):
        hg = []
        hg_dict = {}
        upids = []
        if self.mouse_genes:
            # read MGI:IDs and get mapped HGNC:IDs
            hg = self._load_mouse_genes(fname)
        else:
            # read HGNC:IDs or HGNC gene symbols
            hg = load_genes(fname)
        # human gene symbols as input
        if re.match('^[A-Za-z]', hg[0]):
            hgncids = []
            for gsymbol in hg:
                hgnc_id = hgnc_client.get_hgnc_id(gsymbol)
                if not hgnc_id:
                    logger.info('Not included for analysis: could not '
                                'find hgnc:id corresponding to %s' % gsymbol)
                    hg.remove(gsymbol)
                    continue
                hgncids.append(hgnc_id)
                up_id = hgnc_client.get_uniprot_id(hgnc_id)
                if not up_id:
                    logger.info('Could not find uniprot_id'
                                ' corresponding to hgnc %s' % hgnc_id)
                    up_id = ''
                upids.append(up_id)
            hg_dict['Symbol'] = hg
            hg_dict['HGNC'] = hgncids
        # hg contains HGNC IDs
        else:
            hsymbol = []
            for hgnc_id in hg:
                gsymbol = hgnc_client.get_hgnc_name(hgnc_id)
                if not gsymbol:
                    logger.info('Not included for analysis: could not find'
                                ' human gene symbol corresponding to %s' %
                                hgnc_id)
                    hg.remove(hgnc_id)
                    continue
                hsymbol.append(gsymbol)
                up_id = hgnc_client.get_uniprot_id(hgnc_id)
                if not up_id:
                    logger.info('Could not find uniprot_id corresponding to'
                                ' hgnc %s' % hgnc_id)
                    up_id = ''
                upids.append(up_id)
            hg_dict['HGNC'] = hg
            hg_dict['Symbol'] = hsymbol
        hg_dict['UP'] = upids
        hgdf = pd.DataFrame(hg_dict)
        return hgdf
    
    def _load_mouse_genes(self,fname):
        """Returns a list with mapped human gene IDs"""
        mgis= load_genes(fname)
        hgenes = []
        for mgi_id in mgis:
            if mgi_id.startswith('MGI:'):
                mgi_id = mgi_id[4:]
            hgnc_id = hgnc_client.get_hgnc_from_mouse(mgi_id)
            if not hgnc_id:
                logger.info('Could not find human gene corresponding to MGI %s' % mgi_id)
                continue
            hgenes.append(hgnc_id)
        return hgenes
    
    def MG_from_PC(self):
        """Assemble a nx.MultiGraph from the Pathway Commons sif file
        (nodeA <relationship type> nodeB).
        """
        gwn_df = pd.read_csv(get_pc(), sep='\t', dtype=str, header=None)
        col_mapper = {}
        col_mapper[0] = 'source'
        col_mapper[1] = 'rel_type'
        col_mapper[2] = 'target'
        edge_attributes=True           
        gwn_df=gwn_df.rename(mapper=col_mapper, axis='columns')
        pc = nx.from_pandas_edgelist(gwn_df, source='source', target='target',
                                     edge_attr=edge_attributes,
                                     create_using=nx.MultiGraph)
        # subset over genes in the input gene list
        pc_sub = pc.subgraph(list(self.hgenes['Symbol']))
        gene2hgnc_dict = dict(zip(self.hgenes['Symbol'], self.hgenes['HGNC']))
        nx.set_node_attributes(pc_sub, gene2hgnc_dict, 'HGNC')
        gene2up_dict = dict(zip(self.hgenes['Symbol'], self.hgenes['UP']))
        nx.set_node_attributes(pc_sub, gene2up_dict, 'UP')
        # make a copy to unfreeze graph
        self.graph=nx.MultiGraph(pc_sub)

    def add_GOannotations(self):
        """Add to self.graph the GO annotations (GO:IDs) of proteins (ie, the
        subset of self.graph nodes that contain UniprotKB:ID) in the form of
        labeled edges (see _GOA_from_UP for details) and new nodes (GO:IDs).
        """
        self.GOA = pd.read_csv(get_goa_gaf(), sep='\t', skiprows=23, dtype=str,
                               header=None,
                        names=['DB',
                               'DB_ID',
                               'DB_Symbol',
                               'Qualifier',
                               'GO_ID',
                               'DB_Reference',
                               'Evidence_Code',
                               'With_From',
                               'Aspect',
                               'DB_Object_Name',
                               'DB_Object_Synonym',
                               'DB_Object_Type',
                               'Taxon',
                               'Date',
                               'Assigned',
                               'Annotation_Extension',
                               'Gene_Product_Form_ID'])
        self.GOA = self.GOA.sort_values(by=['DB_ID','GO_ID'])
        self.OGO = GODag(get_go_obo())  # dict
        PC_nodes = list(nx.nodes(self.graph))
        N = len(PC_nodes)
        j = 0  # counter for duration
        for n in PC_nodes: 
            if j % 100 == 0:
                logger.info("%d / %d" % (j , N))
            if 'UP' in self.graph.node[n].keys():  # node is PC gene/protein
                UP = self.graph.node[n]['UP']
                GOan = self._GOA_from_UP(UP)
                for i in GOan.index:
                    GOID = GOan['GO_ID'][i]
                    eattr = GOan['Qualifier'][i]
                    if self.OGO[GOID].is_obsolete is False:
                        self._add_GOnode(GOID)
                        self._add_edge(n,GOID,eattr)
            j = j + 1
                     
    def add_GOontology(self):
        """Add to self.graph the GO ontology (GO:IDs and their relations) in
        the form of labeled edge (relation type, eg is_a) and new nodes
        (GO:IDs).
        """
        for goid in self.OGO.keys():
            GOT = self.OGO[goid]
            if GOT.is_obsolete is False:
                self._add_GOnode(GOT.id)
                for pa in GOT.parents:
                    if pa.is_obsolete is False:
                        self._add_GOnode(pa.id)
                        self._add_edge(GOT.id,pa.id,'GO:is_a')
    
    def _GOA_from_UP(self, UP):
        # UP matching GOIDs and Qualif
        SEL = \
            self.GOA[self.GOA['DB_ID'] == UP][['GO_ID', 'Evidence_Code']].drop_duplicates()
        for i in SEL.index:
            if (SEL['Evidence_Code'][i] in self.EC_GOA) & (SEL['GO_ID'][i]
                                                           in self.OGO):
                pass
            else:
                # Insufficient evidence for annotation or not present in OGO:
                # obsolete GO:ID, so drop.
                SEL = SEL.drop(i)
        # add new column
        SEL.insert(loc=1, column='Qualifier',
                   value=pd.Series('GOan', index=SEL.index))
        return SEL.drop(columns=['Evidence_Code'])

    def _add_GOnode(self, GOID):
        GOT = self.OGO[GOID]
        nameGO = GOT.name
        nameGO = nameGO.replace(" ","_")
        # nx ensures no duplicate nodes with same key will be created
        self.graph.add_node(GOID, name=nameGO, GO=GOID)
        
    def _add_edge(self, s, t, edge_attributes=None):
        if edge_attributes is None:
            self.graph.add_edge(s, t, label='NA')
        else:
            self.graph.add_edge(s, t, label=edge_attributes)
          
    def node2edges(self, node_key):
        return self.graph.edges(node_key, keys=True)
    
    def save_graph(self, folder='~/genewalk/', filepath='gwn'):
        nx.write_graphml(self.graph, os.path.join(folder, filepath + '.xml'))
        
        

        
class Nx_MG_Assembler_INDRA(object):
    """The Nx_MG_Assembler_INDRA assembles INDRA Statements and GO ontology /
    annotations into a networkx (undirected) MultiGraph including edge
    attributes. This code is based on INDRA's SifAssembler
    http://indra.readthedocs.io/en/latest/_modules/indra/assemblers/sif_assembler.html

    Parameters
    ----------
    stmts : Optional[list[indra.statements.Statement]]
        A list of INDRA Statements to be added to the assembler's list
        of Statements.

    Attributes
    ----------
    graph : networkx.MultiGraph
        A GeneWalk Network that is assembled by this assembler.
    GOA : pandas.DataFrame
        GO annotation in pd.dataframe format
    OGO : goatools.GODag
        GO ontology, GODag object (see goatools)
    """
    def __init__(self, stmts=None):
        self.stmts = [] if stmts is None else stmts
        self.graph = nx.MultiGraph()
        self.GOA = []
        self.OGO = []
        self.EC_GOA=['EXP', 'IDA', 'IPI', 'IMP', 'IGI', 'IEP', 'HTP', 'HDA',
                     'HMP', 'HGI', 'HEP', 'IBA', 'IBD']

    def MG_from_INDRA(self):
        """Assemble the graph from the assembler's list of INDRA Statements. 
        Edge attribute are given by statement type and index in list of stmts
        """
        N=len(self.stmts)
        for i in range(N):
            if i % 1000 == 0:
                logger.info("%d / %d" % (i, N))
            st = self.stmts[i]
            # Get all agents in the statement
            agents = st.agent_list()
            # Filter out None Agent
            agents = [a for a in agents if a is not None]
            # Only include edges for statements with at least 2 Agents
            # excludes (irrelevant) stmt types: Translocation, ActiveForm,
            # SelfModification
            if len(agents) < 2:
                continue
            edge_attr = str(i)+'_'+type(st).__name__
            # Iterate over all the agent combinations and add edge
            for a, b in itertools.combinations(agents, 2):
                self._add_INnode_edge(a, b, edge_attr)

    def add_FPLXannotations(self,filename):
        """Add to self.graph an edge (label: 'FPLX:is_a') between the gene
        family to member annotation edges.

        Parameters
        ----------
        filename : str specifying the .csv file with list of tuples with the
        first element of the tuple a child gene name or FamPlex entry, and the
        second element a parent FamPlex entry, e.g. ('KRAS', 'RAS')
        """
        FPLX = pd.read_csv(filename, sep=',', dtype=str, header=None)
        # Add protein family/complex links
        for i in FPLX.index:
            s = FPLX[0][i]
            t = FPLX[1][i]
            edge_attr = 'FPLX:is_a'
            self._add_edge(s, t, edge_attr)

    def add_GOannotations(self):
        """Add to self.graph the GO annotations (GO:IDs) of proteins (ie, the
        subset of self.graph nodes that contain UniprotKB:ID) in the form of
        labeled edges (see _GOA_from_UP for details) and new nodes (GO:IDs).
        """
        self.GOA = pd.read_csv(get_goa_gaf(), sep='\t', skiprows=23,
                               dtype=str, header=None,
                 names=['DB',
                        'DB_ID',
                        'DB_Symbol',
                        'Qualifier',
                        'GO_ID',
                        'DB_Reference',
                        'Evidence_Code',
                        'With_From',
                        'Aspect',
                        'DB_Object_Name',
                        'DB_Object_Synonym',
                        'DB_Object_Type',
                        'Taxon',
                        'Date',
                        'Assigned',
                        'Annotation_Extension',
                        'Gene_Product_Form_ID'])
        self.GOA = self.GOA.sort_values(by=['DB_ID','GO_ID'])
        self.OGO = GODag(get_go_obo())
        IN_nodes = list(nx.nodes(self.graph))
        N = len(IN_nodes)
        j = 0  # counter for duration
        for n in IN_nodes: 
            if j % 100 == 0:
                logger.info("%d / %d" % (j , N))
            # node is INDRA gene/protein
            if 'UP' in self.graph.node[n].keys():
                UP = self.graph.node[n]['UP']
                GOan = self._GOA_from_UP(UP)
                for i in GOan.index:
                    GOID = GOan['GO_ID'][i]
                    eattr = GOan['Qualifier'][i]
                    if self.OGO[GOID].is_obsolete is False:
                        self._add_GOnode(GOID, '0')
                        self._add_edge(n, GOID, eattr)
            j = j + 1

    def add_GOontology(self):
        """Add to self.graph the GO ontology (GO:IDs and their relations) in
        the form of labeled edge (relation type, eg is_a) and new nodes
        (GO:IDs).
        """
        for goid in self.OGO.keys():
            GOT=self.OGO[goid]
            if GOT.is_obsolete is False:
                self._add_GOnode(GOT.id,'0')
                for pa in GOT.parents:
                    if pa.is_obsolete is False:
                        self._add_GOnode(pa.id,'0')
                        self._add_edge(GOT.id,pa.id,'GO:is_a')

    def _GOA_from_UP(self, UP):
        # UP matching GOIDs and Qualif
        SEL = \
            self.GOA[self.GOA['DB_ID'] == UP][['GO_ID','Evidence_Code']].drop_duplicates()
        for i in SEL.index:
            if (SEL['Evidence_Code'][i] in self.EC_GOA) & (SEL['GO_ID'][i] in
                                                           self.OGO):
                pass
            else:
                # Insufficient evidence for annotation or not present in OGO:
                # obsolete GO:ID, so drop.
                SEL = SEL.drop(i)
        # add new column
        SEL.insert(loc=1, column='Qualifier',
                   value=pd.Series('GOan', index=SEL.index))
        return SEL.drop(columns=['Evidence_Code'])

    def _add_INnode_edge(self, s, t, attributes):
        if s is not None:
            s = self._add_INnode(s)
            t = self._add_INnode(t)
            self._add_edge(s, t, attributes)

    def _add_INnode(self, ag):
        if 'GO' in ag.db_refs:
            node_key = ag.db_refs['GO']
            # double check if GO: is present in GO:ID
            if re.search(r'GO:', node_key) is None:
                node_key = 'GO:' + node_key
            self._add_GOnode(node_key, '1')
            # copy over any other identifiers (UP,HGNC,GO,TXT,ChEBI etc)
            # as node attr.
            for attr in ag.db_refs.keys():
                if attr != 'GO':
                    self.graph.node[node_key][attr]=ag.db_refs[attr]
        else:
            node_key = ag.name
            self.graph.add_node(node_key,name=node_key,INDRA='1')
            # copy over the identifiers (UP,HGNC,TXT,ChEBI etc) as node
            # attribute
            for attr in ag.db_refs.keys():
                self.graph.node[node_key][attr]=ag.db_refs[attr]
        return node_key

    def _add_GOnode(self, GOID, indra):
        GOT = self.OGO[GOID]
        nameGO = GOT.name
        nameGO = nameGO.replace(" ", "_")
        self.graph.add_node(GOID, name=nameGO, GO=GOID) # nx ensures no
        # duplicate nodes with same key will be created
        # not yet present, so assign origin: INDRA or GOA/OGO
        if 'INDRA' not in self.graph.node[GOID].keys():
            self.graph.node[GOID]['INDRA'] = indra

    def _add_edge(self, s, t, edge_attributes=None):
        if edge_attributes is None:
            self.graph.add_edge(s, t, label='NA')
        else:
            self.graph.add_edge(s, t, label=edge_attributes)

    def node2stmts(self, node_key):
        matching_stmts = []
        node_name=self.graph.node[node_key]['name']
        for stmt in self.stmts:
            for agent in stmt.agent_list():
                if agent is not None:
                    agent_name = agent.name
                    if agent_name == node_name:
                        matching_stmts.append(stmt)
                        break
        return matching_stmts

    def node2edges(self, node_key):
        return self.graph.edges(node_key, keys=True)

    def save_graph(self, folder='~/genewalk/', filename='gwn'):
        nx.write_graphml(self.graph, folder + filename + '.xml')


class Nx_MG_Assembler_fromUser(object):
    """The Nx_MG_Assembler_fromUser loads a user-provided GeneWalk Network from
    file.

    Parameters
    ----------
    filepath : Optional[str]
        Path to the user-provided genewalk network file, assumed to contain
        gene symbols and GO:IDs. See gwn_format for supported format details.
    gwn_format : Optional[str]
        'el' (default, edge list: nodeA nodeB (if more columns
        present: interpreted as edge attributes) \
        or 'sif' (simple interaction format: nodeA <relationship type> nodeB).
        Do not include column headers.

    Attributes
    ----------
    graph : networkx.MultiGraph
        A GeneWalk Network that is loaded by this assembler.
    """
    # TODO: reimplement this as a method in main assembler class?
    # TODO: gwn_format is unused here
    def __init__(self, filepath='~/genewalk/gwn.txt', gwn_format='el'):
        self.graph = nx.MultiGraph()
        self.filepath = filepath
        
    def MG_from_file(self):
        """Assemble the GeneWalk Network from the user-provided file path."""
        gwn_df = pd.read_csv(self.filepath, dtype=str, header=None)
        col_mapper = {}
        if self.gwn_format == 'el':
            col_mapper[0] = 'source'
            col_mapper[1] = 'target'
            if len(gwn_df.columns) > 2:
                col_mapper[2] = 'rel_type'
                if len(gwn_df.columns) > 3:
                    for c in gwn_df.columns[3:]:
                        col_mapper[c] = 'edge_attr'+str(c-1)
                edge_attributes = True
            else:
                edge_attributes = False
        elif self.gwn_format == 'sif':
            col_mapper[0] = 'source'
            col_mapper[1] = 'rel_type'
            col_mapper[2] = 'target'
            edge_attributes = True
            
        gwn_df.rename(mapper=col_mapper,axis='columns')
        self.graph = nx.from_pandas_edgelist(gwn_df, 'source', 'target',
                                             edge_attr=edge_attributes,
                                             create_using=nx.MultiGraph)

    def node2edges(self, node_key):
        return self.graph.edges(node_key,keys=True)        
