# STUB(INFRA-01): static placeholder on :3000; FE-01 replaces this with the Next.js app.
FROM nginx:1.27-alpine
RUN sed -i 's/listen       80;/listen 3000;/' /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
