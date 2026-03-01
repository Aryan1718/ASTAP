FROM node:20-alpine

WORKDIR /app

COPY client/package.json /app/package.json
COPY client/package-lock.json /app/package-lock.json
RUN npm ci

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
