# ── Build stage: the only moment this project touches npm ────────────────────
FROM node:20-alpine AS build
WORKDIR /build

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY vite.config.js index.html ./
COPY src ./src
COPY public ./public
RUN npm run build

# ── Runtime: static files on nginx. No Node, no network calls. ───────────────
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
