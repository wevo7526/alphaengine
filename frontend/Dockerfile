FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Build-time env vars for Next.js (baked into the JS bundle)
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL

RUN npm run build

# Railway assigns $PORT dynamically — must not hardcode
ENV PORT=3000

CMD ["sh", "-c", "npx next start -p $PORT"]
