#!/usr/bin/env python3
import signal, sys, os, getopt

d = os.path.dirname(sys.argv[0])
sys.path.append(d)
pid_dir = "/tmp"

import pywind.evtframework.evt_dispatcher as dispatcher
import fdslight_etc.fn_server as fns_config
import fdslight_etc.fn_client as fnc_config
import freenet.lib.fdsl_ctl as fdsl_ctl
import freenet.handler.dns_proxy as dns_proxy
import freenet.handler.tundev as tundev
import freenet.lib.file_parser as file_parser
import freenet.lib.fn_utils as fn_utils

FDSL_PID_FILE = "fdslight.pid"
FDSL_DNS_PID_FILE = "fdslight_dns.pid"

__mode = "client"


def create_pid_file(fname, pid):
    pid_path = "%s/%s" % (pid_dir, fname)
    fd = open(pid_path, "w")
    fd.write(str(pid))
    fd.close()


def get_process_id(fname):
    pid_path = "%s/%s" % (pid_dir, fname)
    if not os.path.isfile(pid_path):
        return -1
    fd = open(pid_path, "r")
    pid = fd.read()
    fd.close()

    return int(pid)


def clear_pid_file():
    for s in [FDSL_PID_FILE, FDSL_DNS_PID_FILE]:
        pid_path = "%s/%s" % (pid_dir, s)
        if os.path.isfile(pid_path):
            os.remove(pid_path)
        continue
    return


class fdslight(dispatcher.dispatcher):
    __vir_nc_fileno = -1
    __tunnelc = None
    __tunnelc_fileno = -1
    __tunnels_fileno = -1
    __dns_fileno = -1

    __debug = True

    def __create_fn_tcp_server(self, tunnels):
        fn_s_no = self.create_handler(-1, tunnels.tcp_tunnel)

        self.__tunnels_fileno = fn_s_no
        self.get_handler(fn_s_no).after()

    def __client_get_whitelist(self):
        """获取白名单"""
        results = file_parser.parse_ip_subnet_file("fdslight_etc/whitelist.txt")
        return results

    def __create_fn_tcp_client(self, tunnelc):
        os.chdir("driver")
        if not os.path.isfile("fdslight.ko"):
            print("you can install this software")
            sys.exit(-1)

        path = "/dev/%s" % fdsl_ctl.FDSL_DEV_NAME
        if os.path.exists(path):
            os.system("rmmod fdslight")
        os.system("insmod fdslight.ko")

        os.chdir("../")
        self.__tunnelc = tunnelc
        self.__tunnelc_fileno = self.create_handler(-1, tunnelc.tcp_tunnel, self.__client_get_whitelist())
        self.get_handler(self.__tunnelc_fileno).after(self.__vir_nc_fileno)

    def __create_client_vir_nc(self):
        """创建客户端虚拟网卡"""
        nc_fileno = self.create_handler(-1, tundev.tunc, fn_utils.TUN_DEV_NAME)
        self.__vir_nc_fileno = nc_fileno

    def __create_dns_proxy(self):
        rules = file_parser.parse_host_file("fdslight_etc/blacklist.txt")
        self.__dns_fileno = self.create_handler(-1, dns_proxy.dns_proxy, rules, debug=self.__debug)

    def init_func(self, mode, debug=True):
        if mode == "server":
            t = fns_config.configs["tunnels"]
            name = "freenet.tunnels.%s" % t
        if mode == "client":
            t = fnc_config.configs["tunnelc"]
            name = "freenet.tunnelc.%s" % t
        __import__(name)
        tunnel = sys.modules[name]

        self.__debug = debug

        if debug:
            self.__debug_run(mode, tunnel)
            return

        self.__run(mode, tunnel)

    def client_need_reconnect(self):
        """由客户端handler调用,告知需要重新连接隧道"""
        tunnel_fd = self.create_handler(-1, self.__tunnelc.tcp_tunnel, [])

        self.__tunnelc_fileno = tunnel_fd
        self.get_handler(tunnel_fd).after(self.__vir_nc_fileno)

    def __alrm_sig_handle_for_dns_proxy(self, signum, frame):
        self.__create_dns_proxy()

    def ___create_client_service(self, tunnel):
        pid = os.fork()
        if pid == 0:
            if not self.__debug: create_pid_file(FDSL_PID_FILE, os.getpid())
            self.create_poll()
            self.__create_client_vir_nc()
            self.__create_fn_tcp_client(tunnel)
            self.get_handler(self.__vir_nc_fileno).set_tunnel_fileno(self.__tunnelc_fileno)
            os.kill(os.getppid(), signal.SIGALRM)
            return

        if not self.__debug: create_pid_file(FDSL_DNS_PID_FILE, os.getpid())
        self.create_poll()
        signal.signal(signal.SIGALRM, self.__alrm_sig_handle_for_dns_proxy)

    def __create_server_service(self, tunnel):
        if not self.__debug: create_pid_file(FDSL_PID_FILE, os.getpid())
        self.create_poll()
        self.__create_fn_tcp_server(tunnel)

    def __debug_run(self, mode, module):
        if mode == "server": self.__create_server_service(module)
        if mode == "client": self.___create_client_service(module)

    def __run(self, mode, module):
        pid = os.fork()
        if pid != 0: sys.exit(0)

        os.setsid()
        os.umask(0)
        pid = os.fork()

        if pid != 0: sys.exit(0)

        if mode == "server":
            sys.stdout = open(fns_config.configs["access_log"], "a+")
            sys.stderr = open(fns_config.configs["error_log"], "a+")
            self.__create_server_service(module)

        if mode == "client":
            sys.stdout = open(fnc_config.configs["access_log"], "a+")
            sys.stderr = open(fnc_config.configs["error_log"], "a+")

            self.___create_client_service(module)
            return

        return

    def finish_dns_process(self):
        if self.__debug:
            os.kill(os.getpid(), signal.SIGINT)
            return

        pid = get_process_id(FDSL_DNS_PID_FILE)
        if pid > 0: os.kill(pid, signal.SIGINT)


def stop_service():
    pid = get_process_id(FDSL_PID_FILE)
    if pid < 1: return
    os.kill(pid, signal.SIGINT)
    if __mode == "client": pid = get_process_id(FDSL_DNS_PID_FILE)
    if pid < 1: return
    os.kill(pid, signal.SIGINT)


def main():
    help_doc = """
    -m   client | server
    -d   stop   | start | debug
    """
    try:
        opts, args = getopt.getopt(sys.argv[1:], "m:d:")
    except getopt.GetoptError:
        print(help_doc)
        return
    m = ""
    d = ""
    for k, v in opts:
        if k == "-d":
            d = v
        if k == "-m":
            m = v
        continue

    if not m or not d:
        print(help_doc)
        return

    if d not in ["stop", "start", "debug"]:
        print(help_doc)
        return

    if m not in ["client", "server"]:
        print(help_doc)
        return

    if d == "stop":
        stop_service()
        return

    debug = False
    if d == "debug": debug = True

    fdslight_ins = fdslight()
    __mode = m

    try:
        fdslight_ins.ioloop(m, debug=debug)
    except KeyboardInterrupt:
        clear_pid_file()
        sys.stdout.flush()
        sys.stdout.close()
        sys.stderr.close()

    return


if __name__ == '__main__':
    main()
