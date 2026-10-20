FROM node:24-alpine AS build
WORKDIR /web
RUN corepack enable && corepack prepare pnpm@12.6.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN pnpm build

FROM nginx:1.27-alpine
ENV OWNSTACK_EDGE_INTERNAL_IP=127.0.0.1
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
