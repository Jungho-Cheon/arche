# 사내 인프라 배치 가이드 — Kubernetes (ADR-0015 D5)

> 본 가이드는 ADR-0015 의 *사내 인프라 활용 + 공유 KB* MVP 조건 (4) 의 구체적 배치 경로. 사용자의 사내 환경 (Open Question 11) 이 Kubernetes 기반인 경우의 골격.

## 사전 조건

- Kubernetes 클러스터 (1.28+)
- `kubectl` 설정 + 적절한 namespace 권한
- 사내 LLM gateway 또는 OpenAI API access (Secret 으로 주입)
- Ingress controller (nginx-ingress / Traefik)

## 컴포넌트

| 컴포넌트 | 종류 | 비고 |
|---|---|---|
| `arche-api` | Deployment | FastAPI + MCP HTTP transport |
| `arche-neo4j` | StatefulSet | Neo4j 5.15 (또는 Aura 외부) |
| `arche-cache` | PVC | ADR-0010 의 청크 캐시 (`.arche-cache/`) — `ReadWriteMany` |
| `arche-secrets` | Secret | OPENAI_API_KEY / NEO4J_PASSWORD |
| `arche-config` | ConfigMap | 모델 ID / batch 크기 / namespace 기본 정책 |
| Ingress | Ingress | `/v1/*` (REST) + `/mcp/v1/*` (MCP HTTP) |

## Manifest 골격

### Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: arche-secrets
  namespace: arche
type: Opaque
stringData:
  OPENAI_API_KEY: "<설정>"
  NEO4J_PASSWORD: "<설정>"
```

### Neo4j StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: arche-neo4j
spec:
  serviceName: arche-neo4j
  replicas: 1
  selector:
    matchLabels: { app: arche-neo4j }
  template:
    metadata:
      labels: { app: arche-neo4j }
    spec:
      containers:
      - name: neo4j
        image: neo4j:5.15-community
        ports:
        - { name: bolt, containerPort: 7687 }
        - { name: http, containerPort: 7474 }
        env:
        - name: NEO4J_AUTH
          valueFrom:
            secretKeyRef: { name: arche-secrets, key: NEO4J_PASSWORD }
        volumeMounts:
        - { name: data, mountPath: /data }
  volumeClaimTemplates:
  - metadata: { name: data }
    spec:
      accessModes: [ReadWriteOnce]
      resources: { requests: { storage: 50Gi } }
```

### API Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: arche-api
spec:
  replicas: 2
  selector:
    matchLabels: { app: arche-api }
  template:
    metadata:
      labels: { app: arche-api }
    spec:
      containers:
      - name: api
        image: arche-api:latest
        ports:
        - { name: http, containerPort: 8000 }
        env:
        - name: NEO4J_URI
          value: "bolt://arche-neo4j:7687"
        - name: NEO4J_USER
          value: "neo4j"
        - name: NEO4J_PASSWORD
          valueFrom:
            secretKeyRef: { name: arche-secrets, key: NEO4J_PASSWORD }
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef: { name: arche-secrets, key: OPENAI_API_KEY }
        envFrom:
        - configMapRef: { name: arche-config }
        volumeMounts:
        - { name: cache, mountPath: /workspace/.arche-cache }
        readinessProbe:
          httpGet: { path: /healthz, port: 8000 }
          periodSeconds: 5
      volumes:
      - name: cache
        persistentVolumeClaim: { claimName: arche-cache }
```

### PVC + ConfigMap + Service + Ingress

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: arche-cache
spec:
  accessModes: [ReadWriteMany]  # 여러 replica 공유
  resources: { requests: { storage: 20Gi } }
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: arche-config
data:
  ARCHE_API_LLM_MODEL: "openai/gpt-4.1"
  ARCHE_API_EMBEDDING_MODEL: "openai/text-embedding-3-small"
  INGEST_BATCH_SIZE: "8"
---
apiVersion: v1
kind: Service
metadata: { name: arche-api }
spec:
  selector: { app: arche-api }
  ports:
  - { port: 80, targetPort: 8000 }
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: arche
  annotations:
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"  # ingest task
spec:
  rules:
  - host: arche.internal
    http:
      paths:
      - { path: /, pathType: Prefix, backend: { service: { name: arche-api, port: { number: 80 } } } }
```

## 인증 게이트웨이 (ADR-0014 D3)

본 시제품 단계 default `ns:<id>` 토큰은 *PoC 용*. 사내 환경 도입 시:

1. **사내 SSO 통합** — OAuth2/OIDC sidecar (oauth2-proxy / Pomerium). 검증 후 `X-Forwarded-User`, `X-Forwarded-Email` 헤더 → ADR-0014 D3 의 `auth_context_dep` 가 그 헤더로 namespace 결정.
2. **API key store** — Vault / AWS Secrets Manager 에 API key → namespace 매핑.

본 PR 의 `parse_authorization_header` 는 *주입 포인트* — 위 두 방식 모두 같은 인터페이스 (AuthContext 반환) 로 교체.

## 운영 가시성

- `/healthz` — k8s readiness/liveness.
- `/admin/namespaces` (예정) — namespace 별 entity / chunk 수.
- Prometheus metrics (예정) — ingest 시간 / LLM 토큰 / cache hit rate.

## 검증 시나리오 (사용자 사내 배치 후)

| 시나리오 | 기대 동작 |
|---|---|
| 두 사용자가 다른 토큰 (`ns:work-a`, `ns:work-b`) 으로 같은 corpus ingest | 두 namespace 가 독립 그래프 |
| 같은 사용자가 같은 토큰으로 같은 파일 두 번 ingest | 두 번째 short-circuit (source_hash 일치) — 캐시 hit |
| MCP HTTP 호출 (`POST /mcp/v1/`) | 6 graph primitive 모두 정상 응답 |
| MCP stdio (`arche mcp serve --stdio`) | HTTP 와 *완전 동일* 응답 (ADR-0014 D2 코드 공유) |

## 후속 작업

- ADR-0015 D6 운영 가시성 — Prometheus exporter (별도 PR)
- Multi-tenant scaling — replica > 1 시 ingest task registry 공유 (현재 in-process)
- Backup / restore (사내 정책 의존)
