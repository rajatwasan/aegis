# Aegis public demo image: anvil + contract deploy + Guardian Console API,
# all in one machine. The frontend is deployed separately (Vercel) and talks
# to this over HTTPS. Build context = repo root:  fly deploy  (fly.toml points here)

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Foundry (anvil + forge), glibc release binaries via foundryup
ENV FOUNDRY_DIR=/opt/foundry
RUN curl -L https://foundry.paradigm.xyz | bash \
    && $FOUNDRY_DIR/bin/foundryup \
    && ln -s $FOUNDRY_DIR/bin/anvil /usr/local/bin/anvil \
    && ln -s $FOUNDRY_DIR/bin/forge /usr/local/bin/forge \
    && ln -s $FOUNDRY_DIR/bin/cast /usr/local/bin/cast

WORKDIR /app

# Python deps first (cache-friendly)
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# Aegis package — editable install so aegis.devstack's REPO_ROOT resolution
# (parents of the source file) keeps pointing at /app, where contracts/ lives.
COPY python/ python/
RUN pip install --no-cache-dir -e python/

# Contracts: build artifacts inside the image. lib/ are git submodules and
# git-integration builders often clone WITHOUT --recursive, so fetch them if
# the context shipped them empty (OZ pinned to v5.1.0 per ADR 001).
COPY contracts/ contracts/
RUN test -f contracts/lib/openzeppelin-contracts/contracts/token/ERC20/ERC20.sol \
    || (rm -rf contracts/lib/openzeppelin-contracts \
        && git clone --depth 1 --branch v5.1.0 \
           https://github.com/OpenZeppelin/openzeppelin-contracts \
           contracts/lib/openzeppelin-contracts)
RUN test -f contracts/lib/forge-std/src/Test.sol \
    || (rm -rf contracts/lib/forge-std \
        && git clone --depth 1 --branch v1.9.6 \
           https://github.com/foundry-rs/forge-std \
           contracts/lib/forge-std)
RUN cd contracts && forge build

# Runtime data the API reads
COPY policies/ policies/
COPY evals/report.md evals/report.md

COPY deploy/start.sh /start.sh
RUN chmod +x /start.sh

ENV AEGIS_API_HOST=0.0.0.0 \
    AEGIS_API_PORT=8080 \
    AEGIS_STATE_DIR=/data/aegis

EXPOSE 8080
CMD ["/start.sh"]
