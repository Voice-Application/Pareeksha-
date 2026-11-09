FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# Optional build secret "ca" = extra CA bundle (only behind a TLS-intercepting proxy; see docker-compose.proxy.yml).
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci
COPY . .
# NEXT_PUBLIC_* is inlined into the client bundle at build time; mirror AUTH_DISABLED so the open
# dashboard (AUTH_DISABLED=1) treats a missing role as admin. Defaults off, so sign-in builds are unaffected.
ARG NEXT_PUBLIC_AUTH_DISABLED=
ENV NEXT_PUBLIC_AUTH_DISABLED=$NEXT_PUBLIC_AUTH_DISABLED
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
