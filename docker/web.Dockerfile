FROM node:24-bookworm-slim

WORKDIR /workspace
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm install --global pnpm@11.19.0

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --ignore-scripts

COPY apps/web apps/web
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=${API_INTERNAL_URL}
ARG MAX_UPLOAD_MB=100
ENV MAX_UPLOAD_MB=${MAX_UPLOAD_MB}
RUN pnpm --filter @researchos/web build

EXPOSE 3000
CMD ["pnpm", "--filter", "@researchos/web", "start", "--hostname", "0.0.0.0"]
