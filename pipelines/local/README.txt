# This installation's flows -- content of THIS machine, not of the platform.
# Same layout as /opt/mora02/pipelines/specs (one <name>.json per flow), read
# together with it by the flow library, the builder, the MCP flow tools and
# the vocabulary statistics. The builder saves HERE and only here; the shipped
# flows under pipelines/specs/ change through git. A flow saved here under a
# shipped flow's name shadows it. gitignored except for this file.
#
# Inside the containers this is /data/pipelines/local/specs
# (MORA02_PIPELINE_SPECS_LOCAL_DIR overrides).
