FROM node:20-alpine

WORKDIR /app

ENV TZ=Asia/Ho_Chi_Minh

# Cài đặt OpenSSL và múi giờ trên Alpine
RUN apk add --no-cache openssl tzdata

COPY package*.json ./
RUN npm install

COPY prisma ./prisma
RUN npx prisma generate

COPY src ./src
COPY .env* ./

EXPOSE 5000

CMD ["sh", "-c", "npx prisma db push --skip-generate && node src/server.js"]

