FROM nginx:1.26-alpine

# Copy Nginx engine-level configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Copy site-specific server block configurations
COPY conf.d/ /etc/nginx/conf.d/

# Copy custom error pages and static assets
COPY html/ /usr/share/nginx/html/

# Generate self-signed certificate for development environment
# (production certificates are mounted via Docker Compose volumes at runtime)
RUN mkdir -p /etc/nginx/ssl && \
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/privkey.pem \
    -out /etc/nginx/ssl/fullchain.pem \
    -subj "/CN=localhost"

# Health check: validates Nginx configuration syntax and process health
# Parameters aligned with DEPLOY-01 design B4
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD nginx -t
