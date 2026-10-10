FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN CGO_ENABLED=0 go build -o /gateway .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /gateway /app/gateway
EXPOSE 8080
CMD ["/app/gateway"]
