build:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o app-linux .
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -o app-windows.exe .

clean:
	rm -f app-linux app-windows.exe

.PHONY: build clean
