# Web del AVM (F13.4): build con Node 22 y servida con nginx en el 8080. Uso: ver docs/deploy.md.
# Contexto de build: web/ (compose lo configura). VITE_API_URL se incrusta al compilar.

FROM node:22-alpine AS build
WORKDIR /app

# Capa de dependencias: solo se rehace si cambian package.json o package-lock.json.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# URL de la API vista desde el navegador (no desde el contenedor). Sin barra final.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
