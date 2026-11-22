# syntax=docker/dockerfile:1.7
FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.30.7-alpine AS runtime
# OS security fixes published after the base image was built (scanned in CI with Trivy), and an
# unprivileged master process: the pid file moves to /tmp and the `user` directive (root-only) goes.
RUN apk upgrade --no-cache \
 && rm /etc/nginx/conf.d/default.conf \
 && sed -i -e '/^user[[:space:]]/d' -e 's,^pid[[:space:]].*,pid /tmp/nginx.pid;,' /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/nexus.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
