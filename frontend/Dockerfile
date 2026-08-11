FROM node:22-alpine AS build
WORKDIR /app
ARG API_BACKEND_URL=http://localhost:8000
ENV API_BACKEND_URL=$API_BACKEND_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
COPY --from=build /app/next.config.* ./
EXPOSE 3000
CMD ["npm", "run", "start"]
