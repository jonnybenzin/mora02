# OpenClaw gateway for the Mora02 HITL stack (ADR-022).
#
# The image is only the runtime — config and data live in a mounted volume
# (OPENCLAW_CONFIG_PATH / OPENCLAW_STATE_DIR point into it), so the gateway
# keeps its allowlist, plugins, channel and agent across restarts.
#
# Pinned to the version validated in Phase 0. Bump deliberately, never floating.
FROM node:22-slim

# curl: container healthcheck. ca-certificates: outbound TLS for cloud-per-step.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@2026.6.1

# Relocate config + state into the mounted volume at /data/openclaw, so an
# empty image plus a persistent volume is all the gateway needs.
ENV OPENCLAW_CONFIG_PATH=/data/openclaw/openclaw.json \
    OPENCLAW_STATE_DIR=/data/openclaw

WORKDIR /data/openclaw
EXPOSE 18789

# ENTRYPOINT is the binary so `docker compose run --rm mora02-openclaw <args>`
# runs onboarding subcommands (config set / plugins install / channels add)
# against the same volume. The default CMD runs the gateway itself:
#   --bind lan           listen on 0.0.0.0 so Pilot reaches the RPC over
#                        mora02-net (requires auth, supplied via
#                        OPENCLAW_GATEWAY_TOKEN env)
#   --force              clear a stale lock left by an unclean container stop
#   --no-install-daemon  run in the foreground as PID 1, no systemd
ENTRYPOINT ["openclaw"]
CMD ["gateway", "run", "--bind", "lan", "--force"]
