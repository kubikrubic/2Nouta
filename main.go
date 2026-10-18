package main

import (
	"bufio"
	"flag"
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	exitCommand     = "/exit"
	discoverRequest = "NOUTA_DISCOVER"
	discoverReply   = "NOUTA_HERE"
)

func main() {
	port := flag.Int("port", 9000, "TCP-порт сервера")
	flag.Parse()
	if *port < 1 || *port > 65535 {
		fmt.Println("Порт должен быть от 1 до 65535")
		os.Exit(1)
	}

	input := bufio.NewReader(os.Stdin)
	for {
		fmt.Println()
		fmt.Println("1 - Сервер")
		fmt.Println("2 - Клиент")
		fmt.Println("0 - Выход")
		fmt.Print("Выберите пункт: ")

		choice, err := readLine(input)
		if err != nil {
			return
		}
		switch choice {
		case "1":
			runServer(input, *port)
		case "2":
			runClient(input, *port)
		case "0":
			return
		default:
			fmt.Println("Неверный выбор, введите 1, 2 или 0.")
		}
	}
}

func readLine(input *bufio.Reader) (string, error) {
	line, err := input.ReadString('\n')
	if err != nil && line == "" {
		return "", err
	}
	return strings.TrimSpace(line), nil
}

func send(conn net.Conn, text string) error {
	_, err := conn.Write([]byte(text + "\n"))
	return err
}

func runServer(input *bufio.Reader, port int) {
	listener, err := net.Listen("tcp", ":"+strconv.Itoa(port))
	if err != nil {
		fmt.Println("Не удалось запустить сервер:", err)
		return
	}

	fmt.Printf("Сервер слушает порт %d. Адреса этого компьютера:\n", port)
	for _, ip := range localIPs() {
		fmt.Printf("  %s:%d\n", ip, port)
	}
	fmt.Printf("Введённый текст отправляется всем клиентам. %s — остановить сервер.\n", exitCommand)

	responder, err := net.ListenPacket("udp4", ":"+strconv.Itoa(port))
	if err != nil {
		fmt.Println("Автопоиск недоступен:", err)
	} else {
		defer responder.Close()
		go answerDiscovery(responder)
	}

	var mu sync.Mutex
	clients := map[net.Conn]bool{}

	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			mu.Lock()
			clients[conn] = true
			mu.Unlock()
			go func() {
				handleClient(conn)
				mu.Lock()
				delete(clients, conn)
				mu.Unlock()
			}()
		}
	}()

	for {
		line, err := readLine(input)
		if err != nil || line == exitCommand {
			break
		}
		if line == "" {
			continue
		}
		mu.Lock()
		for conn := range clients {
			send(conn, "Сервер: "+line)
		}
		count := len(clients)
		mu.Unlock()
		fmt.Printf("(отправлено клиентам: %d)\n", count)
	}

	listener.Close()
	mu.Lock()
	for conn := range clients {
		conn.Close()
	}
	mu.Unlock()
	fmt.Println("Сервер остановлен.")
}

func handleClient(conn net.Conn) {
	defer conn.Close()
	address := conn.RemoteAddr().String()
	fmt.Println("Подключился клиент", address)
	send(conn, "Подключено к серверу. Пишите сообщения.")

	scanner := bufio.NewScanner(conn)
	for scanner.Scan() {
		message := strings.TrimSpace(scanner.Text())
		if message == "" {
			continue
		}
		fmt.Printf("[%s] %s\n", address, message)
		if send(conn, "Сервер получил: "+message) != nil {
			break
		}
	}
	fmt.Println("Клиент отключился", address)
}

// answerDiscovery отвечает клиентам, которые ищут сервер широковещательным запросом.
func answerDiscovery(conn net.PacketConn) {
	name, _ := os.Hostname()
	buffer := make([]byte, 64)
	for {
		n, from, err := conn.ReadFrom(buffer)
		if err != nil {
			return
		}
		if string(buffer[:n]) == discoverRequest {
			conn.WriteTo([]byte(discoverReply+" "+name), from)
		}
	}
}

// findServer рассылает запрос всем устройствам в локальной сети и возвращает
// адрес сервера, ответившего первым.
func findServer(port int) (string, bool) {
	conn, err := net.ListenPacket("udp4", ":0")
	if err != nil {
		return "", false
	}
	defer conn.Close()

	// 255.255.255.255 Windows отправляет только через один интерфейс,
	// поэтому шлём ещё и на broadcast-адрес каждой сети этого компьютера.
	targets := []net.IP{net.IPv4bcast}
	addresses, _ := net.InterfaceAddrs()
	for _, address := range addresses {
		ipNet, ok := address.(*net.IPNet)
		if !ok || ipNet.IP.To4() == nil || ipNet.IP.IsLoopback() {
			continue
		}
		ip := ipNet.IP.To4()
		broadcast := make(net.IP, 4)
		for i := range ip {
			broadcast[i] = ip[i] | ^ipNet.Mask[len(ipNet.Mask)-4+i]
		}
		targets = append(targets, broadcast)
	}
	for _, ip := range targets {
		conn.WriteTo([]byte(discoverRequest), &net.UDPAddr{IP: ip, Port: port})
	}

	conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	buffer := make([]byte, 256)
	for {
		n, from, err := conn.ReadFrom(buffer)
		if err != nil {
			return "", false
		}
		command, name, _ := strings.Cut(string(buffer[:n]), " ")
		if command != discoverReply {
			continue
		}
		host := from.(*net.UDPAddr).IP.String()
		fmt.Printf("Найден сервер «%s» (%s)\n", name, host)
		return net.JoinHostPort(host, strconv.Itoa(port)), true
	}
}

func localIPs() []string {
	var ips []string
	addresses, _ := net.InterfaceAddrs()
	for _, address := range addresses {
		ipNet, ok := address.(*net.IPNet)
		if ok && !ipNet.IP.IsLoopback() && ipNet.IP.To4() != nil {
			ips = append(ips, ipNet.IP.String())
		}
	}
	if len(ips) == 0 {
		ips = append(ips, "127.0.0.1")
	}
	return ips
}

func runClient(input *bufio.Reader, port int) {
	fmt.Println("Поиск сервера в локальной сети...")
	address, ok := findServer(port)
	if !ok {
		fmt.Println("Сервер не найден.")
		address, ok = askAddress(input, port)
		if !ok {
			return
		}
	}

	fmt.Println("Подключение к", address, "...")
	conn, err := net.DialTimeout("tcp", address, 5*time.Second)
	if err != nil {
		fmt.Println("Не удалось подключиться:", err)
		return
	}
	leaving := make(chan struct{})
	defer conn.Close()
	defer close(leaving) // выполнится раньше conn.Close
	fmt.Printf("Подключено. Введите сообщение и нажмите Enter. %s — вернуться в меню.\n", exitCommand)

	go func() {
		scanner := bufio.NewScanner(conn)
		for scanner.Scan() {
			fmt.Println(scanner.Text())
		}
		select {
		case <-leaving:
		default:
			fmt.Println("Соединение с сервером закрыто. Нажмите Enter, чтобы вернуться в меню.")
			conn.Close()
		}
	}()

	for {
		line, err := readLine(input)
		if err != nil || line == exitCommand {
			return
		}
		if line == "" {
			continue
		}
		if send(conn, line) != nil {
			return
		}
	}
}

func askAddress(input *bufio.Reader, port int) (string, bool) {
	for {
		fmt.Printf("Адрес сервера (IP:порт, Enter — 127.0.0.1:%d): ", port)
		line, err := readLine(input)
		if err != nil {
			return "", false
		}
		if line == "" {
			line = "127.0.0.1"
		}

		host, portText, err := net.SplitHostPort(line)
		if err != nil {
			host, portText = line, strconv.Itoa(port)
		}
		number, err := strconv.Atoi(portText)
		if host == "" || strings.Contains(host, ":") || err != nil || number < 1 || number > 65535 {
			fmt.Println("Неверный адрес, пример: 192.168.0.10:9000")
			continue
		}
		return net.JoinHostPort(host, portText), true
	}
}
