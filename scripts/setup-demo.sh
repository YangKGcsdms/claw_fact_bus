#!/usr/bin/env bash
# Claw Fact Bus 一键 Demo：1 个 Fact Bus + 4 个 OpenClaw（产品/开发/测试/运维）
#
# 用法:
#   export OPENROUTER_API_KEY=sk-or-...
#   curl -fsSL https://raw.githubusercontent.com/YangKGcsdms/claw_fact_bus/main/scripts/setup-demo.sh | bash
#
# 安装后管理（使用 ~/.claw-fact-bus-demo/setup-demo.sh）:
#   ~/.claw-fact-bus-demo/setup-demo.sh --status
#   ~/.claw-fact-bus-demo/setup-demo.sh --logs product
#   ~/.claw-fact-bus-demo/setup-demo.sh --stop
#   ~/.claw-fact-bus-demo/setup-demo.sh --reset
#
# 环境变量见脚本末尾或运行:  bash setup-demo.sh --help

set -euo pipefail

SETUP_VERSION="1.0.0"
SETUP_SCRIPT_URL="${SETUP_SCRIPT_URL:-https://raw.githubusercontent.com/YangKGcsdms/claw_fact_bus/main/scripts/setup-demo.sh}"

CLAW_DEMO_HOME="${CLAW_DEMO_HOME:-$HOME/.claw-fact-bus-demo}"
FACT_BUS_REPO_URL="${FACT_BUS_REPO_URL:-https://github.com/YangKGcsdms/claw_fact_bus.git}"
PLUGIN_REPO_URL="${PLUGIN_REPO_URL:-https://github.com/YangKGcsdms/claw_fact_bus_plugin.git}"
OPENCLAW_REPO_URL="${OPENCLAW_REPO_URL:-https://github.com/openclaw/openclaw.git}"

# Upstream openclaw uses main; many forks use master for this repo + plugin — override with DEMO_*_REF if needed.
DEMO_FACT_BUS_REF="${DEMO_FACT_BUS_REF:-master}"
DEMO_PLUGIN_REF="${DEMO_PLUGIN_REF:-master}"
DEMO_OPENCLAW_REF="${DEMO_OPENCLAW_REF:-main}"

OPENROUTER_MODEL="${OPENROUTER_MODEL:-openai/gpt-4o-mini}"
FACT_BUS_HOST_PORT="${FACT_BUS_HOST_PORT:-28080}"
DEMO_SKIP_BUILD="${DEMO_SKIP_BUILD:-0}"

OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-openclaw:local}"
FACT_BUS_IMAGE="${FACT_BUS_IMAGE:-claw-fact-bus:latest}"

STOP_CLEAN=false

# OpenClaw host ports (fixed; internal 18789)
PORT_PRODUCT=18789
PORT_DEV=18809
PORT_TEST=18829
PORT_OPS=18849

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

warn() {
  echo "WARN: $*" >&2
}

step() {
  echo ""
  echo "==> $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing dependency: $1"
}

usage() {
  cat <<'USAGE'
Claw Fact Bus multi-agent demo installer

Commands:
  (default)     Clone repos, build, generate configs, start stack
  --install     Same as default
  --status      Show container and port status
  --stop        Stop stack (docker compose down)
  --stop --clean   Stop and remove volumes (docker compose down -v)
  --logs [name] Follow logs: fact-bus | product | dev | test | ops (default: all services)
  --reset       Remove demo home directory and exit (re-run install after)
  -h, --help    This help

Environment (install):
  OPENROUTER_API_KEY   Required for install
  CLAW_DEMO_HOME       Demo directory (default: ~/.claw-fact-bus-demo)
  OPENROUTER_MODEL     Model id without openrouter/ prefix (default: openai/gpt-4o-mini)
  FACT_BUS_HOST_PORT   Host port for Fact Bus HTTP (default: 28080)
  DEMO_SKIP_BUILD      Set to 1 to skip docker build if images exist
  DEMO_FACT_BUS_REF    Git ref for claw_fact_bus (default: master)
  DEMO_PLUGIN_REF      Git ref for claw_fact_bus_plugin (default: master)
  DEMO_OPENCLAW_REF    Git ref for openclaw (default: main)
  FACT_BUS_REPO_URL    Override clone URL
  PLUGIN_REPO_URL
  OPENCLAW_REPO_URL
  SETUP_SCRIPT_URL     URL to re-fetch installer copy when piping from curl
USAGE
}

# Resolve DEMO_HOME to absolute path
DEMO_HOME=""
resolve_demo_home() {
  local h="${CLAW_DEMO_HOME/#\~/$HOME}"
  DEMO_HOME=""
  if [[ -d "$h" ]]; then
    DEMO_HOME="$(cd "$h" && pwd)" || DEMO_HOME=""
  fi
}

# Try to checkout ref; if missing, fall back to origin/default branch (main vs master mismatch).
checkout_ref_or_fallback() {
  local dir="$1" ref="$2" name="$3"
  local sh
  sh="$(basename "${BASH_SOURCE[0]:-setup-demo.sh}")"
  if git -C "$dir" checkout "$ref" 2>/dev/null; then
    return 0
  fi
  if git -C "$dir" checkout "origin/$ref" 2>/dev/null; then
    return 0
  fi
  local def
  def="$(git -C "$dir" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')"
  if [[ -n "$def" ]] && git -C "$dir" checkout "$def" 2>/dev/null; then
    warn "Branch \"$ref\" not found in $name; using remote default branch \"$def\". Set DEMO_*_REF to pin."
    return 0
  fi
  for fb in main master; do
    if [[ "$fb" != "$ref" ]] && git -C "$dir" checkout "$fb" 2>/dev/null; then
      warn "Branch \"$ref\" not found in $name; using \"$fb\" instead. Set DEMO_*_REF to pin."
      return 0
    fi
  done
  fail "git checkout failed for $name (wanted \"$ref\"). Try DEMO_*_REF=... or: rm -rf \"$dir\" && $sh --reset"
}

clone_one() {
  local dir="$1" url="$2" ref="$3" name="$4"
  if [[ ! -d "$dir/.git" ]]; then
    step "Cloning $name ($ref)"
    mkdir -p "$(dirname "$dir")"
    if git clone --depth 1 --branch "$ref" --single-branch "$url" "$dir" 2>/dev/null; then
      return 0
    fi
    step "Shallow clone failed; full clone $name"
    git clone "$url" "$dir" || fail "git clone failed for $name"
    checkout_ref_or_fallback "$dir" "$ref" "$name"
  else
    step "Updating $name (fetch + checkout $ref)"
    git -C "$dir" fetch origin "$ref" 2>/dev/null || git -C "$dir" fetch origin || true
    if ! git -C "$dir" checkout "$ref" 2>/dev/null && ! git -C "$dir" checkout "origin/$ref" 2>/dev/null; then
      checkout_ref_or_fallback "$dir" "$ref" "$name"
    fi
    git -C "$dir" pull --ff-only 2>/dev/null || warn "git pull --ff-only failed for $name (non-fatal). If stuck, run --reset."
  fi
}

port_busy() {
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ss -tln | grep -q ":$p " 2>/dev/null || ss -tln | grep -q ":$p]" 2>/dev/null
  else
    return 1
  fi
}

check_ports_free() {
  local ports=("$FACT_BUS_HOST_PORT" "$PORT_PRODUCT" "$PORT_DEV" "$PORT_TEST" "$PORT_OPS")
  local busy=()
  for p in "${ports[@]}"; do
    if port_busy "$p"; then
      busy+=("$p")
    fi
  done
  if [[ ${#busy[@]} -gt 0 ]]; then
    echo "These ports are already in use: ${busy[*]}" >&2
    echo "Free them or set FACT_BUS_HOST_PORT to map Fact Bus elsewhere (OpenClaw ports are fixed in this demo)." >&2
    fail "Port conflict"
  fi
}

save_installer_copy() {
  local dest="$DEMO_HOME/setup-demo.sh"
  mkdir -p "$DEMO_HOME"
  local src="${BASH_SOURCE[0]:-}"
  if [[ -n "$src" ]] && [[ -f "$src" ]] && [[ "$src" != /dev/stdin ]] && [[ "$src" != bash ]]; then
    cp "$src" "$dest"
  else
    step "Downloading installer copy to $dest"
    curl -fsSL "$SETUP_SCRIPT_URL" -o "$dest" || fail "Could not download $SETUP_SCRIPT_URL. Set SETUP_SCRIPT_URL or copy the script manually."
  fi
  chmod +x "$dest"
  echo "Installer saved: $dest"
}

write_version_file() {
  local vf="$DEMO_HOME/.version"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")"
  cat >"$vf" <<VER
setup_version=${SETUP_VERSION}
created_at=${ts}
fact_bus_ref=${DEMO_FACT_BUS_REF}
plugin_ref=${DEMO_PLUGIN_REF}
openclaw_ref=${DEMO_OPENCLAW_REF}
model=openrouter/${OPENROUTER_MODEL}
fact_bus_port=${FACT_BUS_HOST_PORT}
VER
}

wait_http_hard() {
  local url="$1"
  local name="$2"
  local max="${3:-40}"
  local i=0
  while [[ "$i" -lt "$max" ]]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "OK (hard): $name"
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  fail "Timeout (hard): $name — $url"
}

wait_http_soft() {
  local url="$1"
  local name="$2"
  local max="${3:-120}"
  local i=0
  while [[ "$i" -lt "$max" ]]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "OK (soft): $name"
      return 0
    fi
    i=$((i + 1))
    sleep 3
  done
  echo "PENDING (soft): $name — still starting; try: ${DEMO_HOME:-~/.claw-fact-bus-demo}/setup-demo.sh --logs <product|dev|test|ops>" >&2
  return 1
}

check_node_version() {
  local major
  major="$(node -p 'parseInt(process.versions.node.split(".")[0],10)' 2>/dev/null)" || fail "Could not read Node.js version"
  if [[ "$major" -lt 22 ]]; then
    fail "Node.js 22+ required for plugin build (found major=$major)"
  fi
}

install_main() {
  require_cmd docker
  docker info >/dev/null 2>&1 || fail "Docker daemon not running"
  docker compose version >/dev/null 2>&1 || fail "docker compose (v2) required"
  require_cmd node
  require_cmd npm
  check_node_version
  require_cmd openssl
  require_cmd python3
  require_cmd curl
  require_cmd git

  if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    fail "Please export OPENROUTER_API_KEY (OpenRouter API key)."
  fi

  resolve_demo_home
  DEMO_HOME="${CLAW_DEMO_HOME/#\~/$HOME}"
  DEMO_HOME="$(mkdir -p "$DEMO_HOME" && cd "$DEMO_HOME" && pwd)"

  local existing_comp="$DEMO_HOME/docker-compose.yml"
  if [[ -f "$existing_comp" ]]; then
    step "Stopping any existing stack in $DEMO_HOME"
    docker compose -f "$existing_comp" --project-directory "$DEMO_HOME" down 2>/dev/null || true
    sleep 2
  fi

  check_ports_free

  local FACT_BUS_DIR="$DEMO_HOME/claw_fact_bus"
  local PLUGIN_DIR="$DEMO_HOME/claw_fact_bus_plugin"
  local OPENCLAW_DIR="$DEMO_HOME/openclaw"

  clone_one "$FACT_BUS_DIR" "$FACT_BUS_REPO_URL" "$DEMO_FACT_BUS_REF" "claw_fact_bus"
  clone_one "$PLUGIN_DIR" "$PLUGIN_REPO_URL" "$DEMO_PLUGIN_REF" "claw_fact_bus_plugin"
  clone_one "$OPENCLAW_DIR" "$OPENCLAW_REPO_URL" "$DEMO_OPENCLAW_REF" "openclaw"

  step "Building claw_fact_bus_plugin"
  (cd "$PLUGIN_DIR" && npm install && npm run build)

  if [[ "$DEMO_SKIP_BUILD" == "1" ]]; then
    step "Skipping Docker build (DEMO_SKIP_BUILD=1); ensure images: $FACT_BUS_IMAGE, $OPENCLAW_IMAGE"
  else
    step "Building Docker image: $FACT_BUS_IMAGE"
    DOCKER_BUILDKIT=1 docker build -t "$FACT_BUS_IMAGE" -f "$FACT_BUS_DIR/Dockerfile" "$FACT_BUS_DIR"
    step "Building Docker image: $OPENCLAW_IMAGE"
    DOCKER_BUILDKIT=1 docker build -t "$OPENCLAW_IMAGE" -f "$OPENCLAW_DIR/Dockerfile" "$OPENCLAW_DIR"
  fi

  mkdir -p "$DEMO_HOME/roles"/{product,dev,test,ops}/{config,workspace}

  local TOK_PRODUCT TOK_DEV TOK_TEST TOK_OPS
  TOK_PRODUCT="$(openssl rand -hex 16)"
  TOK_DEV="$(openssl rand -hex 16)"
  TOK_TEST="$(openssl rand -hex 16)"
  TOK_OPS="$(openssl rand -hex 16)"
  local PRIMARY_MODEL="openrouter/${OPENROUTER_MODEL}"

  python3 - "$DEMO_HOME/roles" "$PRIMARY_MODEL" "$TOK_PRODUCT" "$TOK_DEV" "$TOK_TEST" "$TOK_OPS" <<'PY'
import json
import sys

roles_dir, primary, t_prod, t_dev, t_test, t_ops = sys.argv[1:7]

roles = {
    "product": {
        "token": t_prod,
        "claw_name": "product-agent",
        "desc": "产品经理：需求与用户价值",
        "capability_offer": ["requirement-analysis", "product-planning", "prioritization"],
        "domain_interests": ["product", "requirement", "user-story"],
        "fact_type_patterns": ["product.*", "requirement.*", "feature.*", "user-story.*"],
        "soul": """# 角色：产品经理

你是一位产品经理。你关注用户需求、路线图、优先级与跨团队对齐。
当 Fact Bus 上出现与你订阅相关的事实时，先理解业务影响，再决定是否需要补充需求或协调资源。
使用 fact_bus_sense 感知新事实，必要时用 fact_bus_publish 推进决策。""",
    },
    "dev": {
        "token": t_dev,
        "claw_name": "dev-agent",
        "desc": "开发工程师：实现与架构",
        "capability_offer": ["coding", "code-review", "architecture-design", "debugging"],
        "domain_interests": ["code", "architecture", "engineering"],
        "fact_type_patterns": ["code.*", "dev.*", "tech.*", "architecture.*", "bug.fix.*"],
        "soul": """# 角色：开发工程师

你是一位开发工程师。你关注实现方案、代码质量、技术债与可维护性。
当 Fact Bus 上出现与你订阅相关的事实时，评估技术可行性并给出实现或评审意见。
使用 fact_bus_sense 感知新事实，用 fact_bus_publish / fact_bus_resolve 推动开发闭环。""",
    },
    "test": {
        "token": t_test,
        "claw_name": "test-agent",
        "desc": "测试工程师：质量与风险",
        "capability_offer": ["testing", "test-planning", "bug-reporting", "quality-assurance"],
        "domain_interests": ["quality", "testing", "qa"],
        "fact_type_patterns": ["test.*", "qa.*", "bug.*", "quality.*", "verification.*"],
        "soul": """# 角色：测试工程师

你是一位测试工程师。你关注测试覆盖、缺陷、回归风险与发布质量。
当 Fact Bus 上出现与你订阅相关的事实时，判断需要哪些验证并反馈质量信号。
使用 fact_bus_sense 感知新事实，用 fact_bus_publish 记录缺陷或验证结果。""",
    },
    "ops": {
        "token": t_ops,
        "claw_name": "ops-agent",
        "desc": "运维工程师：稳定性与交付",
        "capability_offer": ["deployment", "monitoring", "incident-response", "infrastructure"],
        "domain_interests": ["ops", "infrastructure", "deployment", "monitoring"],
        "fact_type_patterns": ["ops.*", "deploy.*", "incident.*", "infra.*", "monitor.*"],
        "soul": """# 角色：运维工程师

你是一位运维工程师。你关注部署、容量、监控、事故响应与 SLO。
当 Fact Bus 上出现与你订阅相关的事实时，评估运行风险与变更窗口。
使用 fact_bus_sense 感知新事实，用 fact_bus_publish / fact_bus_claim 处理需要独占处理的生产事件。""",
    },
}

plugin_path = "/home/node/plugins/claw_fact_bus_plugin"

for role, cfg in roles.items():
    base = os.path.join(roles_dir, role)
    os.makedirs(os.path.join(base, "config"), exist_ok=True)
    os.makedirs(os.path.join(base, "workspace"), exist_ok=True)

    with open(os.path.join(base, "workspace", "SOUL.md"), "w", encoding="utf-8") as f:
        f.write(cfg["soul"])

    oc = {
        "gateway": {"mode": "local", "auth": {"token": cfg["token"]}},
        "agents": {
            "defaults": {
                "workspace": "/home/node/.openclaw/workspace",
                "model": {"primary": primary},
            }
        },
        "plugins": {
            "load": {"paths": [plugin_path]},
            "entries": {
                "fact-bus": {
                    "enabled": True,
                    "config": {
                        "busUrl": "http://fact-bus:8080",
                        "clawName": cfg["claw_name"],
                        "clawDescription": cfg["desc"],
                        "capabilityOffer": cfg["capability_offer"],
                        "domainInterests": cfg["domain_interests"],
                        "factTypePatterns": cfg["fact_type_patterns"],
                        "autoReconnect": True,
                    },
                }
            },
        },
    }

    path = os.path.join(base, "config", "openclaw.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(oc, f, indent=2, ensure_ascii=False)
        f.write("\n")

print("Generated openclaw.json and SOUL.md for product, dev, test, ops.")
PY

  local COMPOSE_FILE="$DEMO_HOME/docker-compose.yml"
  cat >"$COMPOSE_FILE" <<EOF
name: fact-bus-demo

services:
  fact-bus:
    build:
      context: ./claw_fact_bus
      dockerfile: Dockerfile
    image: ${FACT_BUS_IMAGE}
    container_name: fact-bus-demo-bus
    ports:
      - "${FACT_BUS_HOST_PORT}:8080"
    environment:
      - FACT_BUS_DATA_DIR=/data
      - FACT_BUS_HOST=0.0.0.0
      - FACT_BUS_PORT=8080
    volumes:
      - fact-bus-demo-data:/data
    networks:
      - fact-bus-demo
    restart: unless-stopped
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')",
        ]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  openclaw-product:
    image: ${OPENCLAW_IMAGE}
    container_name: fact-bus-demo-openclaw-product
    depends_on:
      fact-bus:
        condition: service_healthy
    environment:
      HOME: /home/node
      TERM: xterm-256color
      TZ: UTC
      OPENROUTER_API_KEY: \${OPENROUTER_API_KEY}
      OPENCLAW_GATEWAY_TOKEN: ${TOK_PRODUCT}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: "1"
    ports:
      - "${PORT_PRODUCT}:18789"
      - "18790:18790"
    volumes:
      - ./roles/product/config:/home/node/.openclaw
      - ./roles/product/workspace:/home/node/.openclaw/workspace
      - ./claw_fact_bus_plugin:/home/node/plugins/claw_fact_bus_plugin:ro
    init: true
    restart: unless-stopped
    command:
      - node
      - dist/index.js
      - gateway
      - --bind
      - lan
      - --port
      - "18789"
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:18789/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
        ]
      interval: 15s
      timeout: 5s
      retries: 8
      start_period: 40s
    networks:
      - fact-bus-demo

  openclaw-dev:
    image: ${OPENCLAW_IMAGE}
    container_name: fact-bus-demo-openclaw-dev
    depends_on:
      fact-bus:
        condition: service_healthy
    environment:
      HOME: /home/node
      TERM: xterm-256color
      TZ: UTC
      OPENROUTER_API_KEY: \${OPENROUTER_API_KEY}
      OPENCLAW_GATEWAY_TOKEN: ${TOK_DEV}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: "1"
    ports:
      - "${PORT_DEV}:18789"
      - "18810:18790"
    volumes:
      - ./roles/dev/config:/home/node/.openclaw
      - ./roles/dev/workspace:/home/node/.openclaw/workspace
      - ./claw_fact_bus_plugin:/home/node/plugins/claw_fact_bus_plugin:ro
    init: true
    restart: unless-stopped
    command:
      - node
      - dist/index.js
      - gateway
      - --bind
      - lan
      - --port
      - "18789"
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:18789/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
        ]
      interval: 15s
      timeout: 5s
      retries: 8
      start_period: 40s
    networks:
      - fact-bus-demo

  openclaw-test:
    image: ${OPENCLAW_IMAGE}
    container_name: fact-bus-demo-openclaw-test
    depends_on:
      fact-bus:
        condition: service_healthy
    environment:
      HOME: /home/node
      TERM: xterm-256color
      TZ: UTC
      OPENROUTER_API_KEY: \${OPENROUTER_API_KEY}
      OPENCLAW_GATEWAY_TOKEN: ${TOK_TEST}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: "1"
    ports:
      - "${PORT_TEST}:18789"
      - "18830:18790"
    volumes:
      - ./roles/test/config:/home/node/.openclaw
      - ./roles/test/workspace:/home/node/.openclaw/workspace
      - ./claw_fact_bus_plugin:/home/node/plugins/claw_fact_bus_plugin:ro
    init: true
    restart: unless-stopped
    command:
      - node
      - dist/index.js
      - gateway
      - --bind
      - lan
      - --port
      - "18789"
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:18789/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
        ]
      interval: 15s
      timeout: 5s
      retries: 8
      start_period: 40s
    networks:
      - fact-bus-demo

  openclaw-ops:
    image: ${OPENCLAW_IMAGE}
    container_name: fact-bus-demo-openclaw-ops
    depends_on:
      fact-bus:
        condition: service_healthy
    environment:
      HOME: /home/node
      TERM: xterm-256color
      TZ: UTC
      OPENROUTER_API_KEY: \${OPENROUTER_API_KEY}
      OPENCLAW_GATEWAY_TOKEN: ${TOK_OPS}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: "1"
    ports:
      - "${PORT_OPS}:18789"
      - "18850:18790"
    volumes:
      - ./roles/ops/config:/home/node/.openclaw
      - ./roles/ops/workspace:/home/node/.openclaw/workspace
      - ./claw_fact_bus_plugin:/home/node/plugins/claw_fact_bus_plugin:ro
    init: true
    restart: unless-stopped
    command:
      - node
      - dist/index.js
      - gateway
      - --bind
      - lan
      - --port
      - "18789"
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:18789/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
        ]
      interval: 15s
      timeout: 5s
      retries: 8
      start_period: 40s
    networks:
      - fact-bus-demo

networks:
  fact-bus-demo:
    driver: bridge

volumes:
  fact-bus-demo-data:
EOF

  write_version_file
  save_installer_copy

  step "Starting stack (Fact Bus + 4x OpenClaw)"
  export OPENROUTER_API_KEY
  docker compose -f "$COMPOSE_FILE" --project-directory "$DEMO_HOME" up -d

  step "Health checks (hard: Fact Bus; soft: OpenClaw)"
  wait_http_hard "http://127.0.0.1:${FACT_BUS_HOST_PORT}/health" "Fact Bus" 40

  wait_http_soft "http://127.0.0.1:${PORT_PRODUCT}/healthz" "OpenClaw product" 120 || true
  wait_http_soft "http://127.0.0.1:${PORT_DEV}/healthz" "OpenClaw dev" 120 || true
  wait_http_soft "http://127.0.0.1:${PORT_TEST}/healthz" "OpenClaw test" 120 || true
  wait_http_soft "http://127.0.0.1:${PORT_OPS}/healthz" "OpenClaw ops" 120 || true

  print_summary "$TOK_PRODUCT" "$TOK_DEV" "$TOK_TEST" "$TOK_OPS"
}

print_summary() {
  local tp="$1" td="$2" tt="$3" to="$4"
  local fb="http://localhost:${FACT_BUS_HOST_PORT}"
  cat <<EOF

================================================================================
Claw Fact Bus Demo
================================================================================
Fact Bus (HTTP, hard check):  ${fb}/health

OpenClaw (soft check — first start may take 2–5 minutes):
  产品 (product)  http://127.0.0.1:${PORT_PRODUCT}/healthz   token: ${tp}
  开发 (dev)      http://127.0.0.1:${PORT_DEV}/healthz       token: ${td}
  测试 (test)     http://127.0.0.1:${PORT_TEST}/healthz      token: ${tt}
  运维 (ops)      http://127.0.0.1:${PORT_OPS}/healthz       token: ${to}

Model: openrouter/${OPENROUTER_MODEL}  (OPENROUTER_API_KEY injected by compose)

Commands:
  ${DEMO_HOME}/setup-demo.sh --status
  ${DEMO_HOME}/setup-demo.sh --logs product
  ${DEMO_HOME}/setup-demo.sh --stop
  ${DEMO_HOME}/setup-demo.sh --reset

Security: API keys are stored under ${DEMO_HOME}/roles/*/config/openclaw.json
         Remove everything:  rm -rf ${DEMO_HOME}

Publish facts (requires source_claw_id; token may be empty ""):
  curl -sS -X POST ${fb}/facts \\
    -H 'Content-Type: application/json' \\
    -d '{"fact_type":"product.requirement.new","payload":{"title":"demo"},"semantic_kind":"request","mode":"broadcast","source_claw_id":"curl-demo","token":""}'

Plugin health (per gateway; use matching port and token from above):
  curl -sS -H "Authorization: Bearer <token>" http://127.0.0.1:${PORT_PRODUCT}/plugins/fact-bus/health

Agents only react when the model session runs tools; WebSocket queues events for fact_bus_sense.
================================================================================
EOF
}

cmd_stop() {
  require_cmd docker
  resolve_demo_home
  [[ -n "$DEMO_HOME" ]] || fail "Demo not installed at ${CLAW_DEMO_HOME:-~/.claw-fact-bus-demo}"
  local cf="$DEMO_HOME/docker-compose.yml"
  [[ -f "$cf" ]] || fail "No docker-compose.yml in $DEMO_HOME"
  if [[ "$STOP_CLEAN" == "true" ]]; then
    docker compose -f "$cf" --project-directory "$DEMO_HOME" down -v
  else
    docker compose -f "$cf" --project-directory "$DEMO_HOME" down
  fi
  echo "Stopped."
}

cmd_status() {
  require_cmd docker
  resolve_demo_home
  [[ -n "$DEMO_HOME" ]] || fail "Demo not installed."
  local cf="$DEMO_HOME/docker-compose.yml"
  [[ -f "$cf" ]] || fail "No docker-compose.yml in $DEMO_HOME"
  docker compose -f "$cf" --project-directory "$DEMO_HOME" ps -a
  echo ""
  echo "Ports: Fact Bus ${FACT_BUS_HOST_PORT:-28080}, OpenClaw ${PORT_PRODUCT}/${PORT_DEV}/${PORT_TEST}/${PORT_OPS}"
  if [[ -f "$DEMO_HOME/.version" ]]; then
    echo "--- $DEMO_HOME/.version ---"
    cat "$DEMO_HOME/.version"
  fi
}

cmd_logs() {
  require_cmd docker
  resolve_demo_home
  [[ -n "$DEMO_HOME" ]] || fail "Demo not installed."
  local cf="$DEMO_HOME/docker-compose.yml"
  [[ -f "$cf" ]] || fail "No docker-compose.yml in $DEMO_HOME"
  local svc=""
  case "${LOG_SERVICE:-}" in
    ""|all) svc="" ;;
    fact-bus) svc="fact-bus" ;;
    product) svc="openclaw-product" ;;
    dev) svc="openclaw-dev" ;;
    test) svc="openclaw-test" ;;
    ops) svc="openclaw-ops" ;;
    *) fail "Unknown service: ${LOG_SERVICE}. Use: fact-bus | product | dev | test | ops" ;;
  esac
  if [[ -z "$svc" ]]; then
    docker compose -f "$cf" --project-directory "$DEMO_HOME" logs -f
  else
    docker compose -f "$cf" --project-directory "$DEMO_HOME" logs -f "$svc"
  fi
}

cmd_reset() {
  require_cmd docker
  local h="${CLAW_DEMO_HOME/#\~/$HOME}"
  local cf="$h/docker-compose.yml"
  if [[ -f "$cf" ]]; then
    docker compose -f "$cf" --project-directory "$h" down -v 2>/dev/null || true
  fi
  rm -rf "$h"
  echo "Removed $h"
  echo "Run install again with OPENROUTER_API_KEY set (e.g. curl ... | bash or bash setup-demo.sh)."
}

# --- Argument parsing ---------------------------------------------------------
ACTION="install"
STOP_CLEAN=false
LOG_SERVICE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stop) ACTION=stop ;;
    --clean) STOP_CLEAN=true ;;
    --status) ACTION=status ;;
    --logs)
      ACTION=logs
      shift
      LOG_SERVICE="${1:-all}"
      [[ $# -gt 0 ]] && shift || true
      break
      ;;
    --reset) ACTION=reset ;;
    --install) ACTION=install ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)" ;;
  esac
  shift
done

if [[ "$STOP_CLEAN" == "true" ]] && [[ "$ACTION" != "stop" ]]; then
  warn "--clean ignored (use with: $0 --stop --clean)"
  STOP_CLEAN=false
fi

case "$ACTION" in
  stop) cmd_stop ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  reset) cmd_reset ;;
  install) install_main ;;
esac
