# Development image (docker-compose.yml) and static build (docker-compose.prod.yml, served by Caddy)
FROM node:20-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM dev AS build
ARG VITE_OPERATOR_NAME
ARG VITE_OPERATOR_ADDRESS
ARG VITE_OPERATOR_EMAIL
RUN npm run build

FROM caddy:2-alpine AS web
COPY --from=build /app/dist /srv
