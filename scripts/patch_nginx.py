"""
/etc/nginx/conf.d/candle.conf 에 stock_index location 블록을 추가하는 스크립트.
이미 추가되어 있으면 건너뜁니다. make nginx-install 에서 sudo 로 실행됩니다.
"""
import sys

CONF = "/etc/nginx/conf.d/candle.conf"
MARKER = "/stock_index"
INSERT_BEFORE = "# ── /news"

BLOCK = """\
    # ── /stock_index — Stock Index 대시보드 (Streamlit) ──────────────────
    location = /stock_index {
        return 301 /stock_index/;
    }

    location /stock_index/ {
        proxy_pass         http://127.0.0.1:8501/stock_index/;
        proxy_http_version 1.1;

        # Streamlit WebSocket 지원
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host               $host;
        proxy_set_header X-Real-IP          $remote_addr;
        proxy_set_header X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto  $scheme;

        proxy_read_timeout 86400;
    }

"""

with open(CONF, "r") as f:
    content = f.read()

if MARKER in content:
    print(f"[skip] {CONF} 에 이미 /stock_index 블록이 존재합니다.")
    sys.exit(0)

if INSERT_BEFORE not in content:
    print(f"[error] '{INSERT_BEFORE}' 를 {CONF} 에서 찾을 수 없습니다.", file=sys.stderr)
    sys.exit(1)

new_content = content.replace(INSERT_BEFORE, BLOCK + INSERT_BEFORE, 1)

with open(CONF, "w") as f:
    f.write(new_content)

print(f"[ok] {CONF} 에 /stock_index 블록을 추가했습니다.")
