ARG DEEPHAVEN_VERSION=42.6
FROM ghcr.io/deephaven/server:${DEEPHAVEN_VERSION}

# graphviz provides the `dot` binary that deephaven.perfmon.ancestor_svg /
# ancestor_image use to render the update-graph ancestry as SVG.
RUN apt-get update \
 && apt-get install -y --no-install-recommends graphviz \
 && rm -rf /var/lib/apt/lists/*
