import sys, rdflib
for f in sys.argv[1:]:
    fmt = "turtle" if f.endswith(".ttl") else "json-ld"
    g = rdflib.Graph()
    try:
        g.parse(f, format=fmt)
        from rdflib.namespace import OWL, RDF
        print(f"{f.rsplit('/',1)[1]}: OK triples={len(g)} classes={len(set(g.subjects(RDF.type, OWL.Class)))} objprops={len(set(g.subjects(RDF.type, OWL.ObjectProperty)))}")
    except Exception as e:
        print(f"{f.rsplit('/',1)[1]}: FAIL {type(e).__name__}: {str(e)[:200]}")
