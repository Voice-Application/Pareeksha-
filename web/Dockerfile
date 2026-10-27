FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# Optional build secret "ca" = extra CA bundle (only behind a TLS-intercepting proxy; see docker-compose.proxy.yml).
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/next.config.ts ./
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0"]
