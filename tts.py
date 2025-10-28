import os
import tkinter as tk
from tkinter import ttk, messagebox, Menu
import threading
import time
import tempfile
import sys 
import uuid 
import asyncio
import pygame
import queue
from PIL import Image, ImageDraw 
import pystray 
import webbrowser
import requests 

# TikTok Live
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent # <--- นี่คือบรรทัดที่ทำให้ CommentEvent ใช้งานได้

# edge-tts
import edge_tts

# =======================================================
# 0. Resource Path & Global Config
# =======================================================

# หมายเลขเวอร์ชันปัจจุบันของโปรแกรม
CURRENT_VERSION = "1.0.0" 
# URL สำหรับตรวจสอบเวอร์ชันล่าสุด (ต้องเข้าถึงได้สาธารณะ)
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/crongcrang/tts-live/refs/heads/main/tts_version.txt" 
# URL สำหรับดาวน์โหลดไฟล์เวอร์ชันใหม่ (ไฟล์ .exe หรือ .zip)
DOWNLOAD_URL = "https://github.com/crongcrang/tts-live/releases/download/python/TTSlive.exe" 

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# =======================================================
# 1. GUI Class
# =======================================================

class TikTokTTSApp:
    
    # เสียงไทยที่ใช้งานได้จริง (2 เสียงหลัก)
    VOICE_OPTIONS = [
        ("ผู้ชาย - Achara (ค่าเริ่มต้น)", "th-TH-AcharaNeural"),
        ("ผู้หญิง - Premwadee", "th-TH-PremwadeeNeural"),
    ]

    # ปรับ Pitch ให้ละเอียดขึ้นเพื่อตัวเลือกที่มากขึ้น
    PITCH_OPTIONS = [
        ("-5", -5),
        ("-3", -3),
        ("-1", -1),
        ("0", 0),
        ("+1", +1),
        ("+3", +3),
        ("+5", +5),
    ]

    # ปรับ Speed ให้ละเอียดขึ้น
    SPEED_OPTIONS = [
        ("0.5", 0.5),
        ("0.75", 0.75),
        ("0.9", 0.9),
        ("1.0", 1.0),
        ("1.1", 1.1),
        ("1.25", 1.25),
        ("1.5", 1.5),
    ]
    
    def __init__(self, master):
        self.master = master
        master.title(f"TikTok Live TTS (Edge TTS) v{CURRENT_VERSION}") 
        master.geometry("620x680") 
        
        try:
            master.iconbitmap(resource_path('app_icon.ico'))
        except: pass

        self.client = None
        self.is_connected = False
        self.log_lock = threading.Lock()
        self.tray_icon = None
        
        self.voice_id = tk.StringVar(value="th-TH-AcharaNeural")
        self.pitch_shift = tk.IntVar(value=0)
        self.speed_rate = tk.DoubleVar(value=1.0)
        
        self.last_generated_file = None
        self.is_generating_tts = threading.Event()
        self.is_custom_tts_active = threading.Event()
        
        self.tts_queue = queue.Queue()
        self.tts_thread = threading.Thread(target=self.tts_worker, daemon=True)
        
        pygame.mixer.pre_init(frequency=24000, size=-16, channels=1, buffer=512)
        pygame.mixer.init()
        self.tts_thread.start()

        self.last_comment_for_skip = None
        self.is_speaking = threading.Event()

        # สถานะการเชื่อมต่อและคิว
        self.status_connection = tk.StringVar(value="Disconnected")
        self.status_speaker = tk.StringVar(value="-")
        self.status_queue_count = tk.StringVar(value="0")
        self.connection_status_label = None

        # ตัวแปรสำหรับสถิติและการควบคุม Live
        self.comments_read_count = tk.IntVar(value=0)
        self.comments_filtered_count = tk.IntVar(value=0)
        self.live_start_time = time.time()
        self.avg_read_rate = tk.StringVar(value="0.00 ข้อความ/นาที")
        self.is_tts_paused = tk.BooleanVar(value=False)

        self.master.bind("<Unmap>", self.on_minimize)
        self.master.protocol("WM_DELETE_WINDOW", self.on_window_close)
        
        self.create_menu_bar()
        
        # จัดเรียงใหม่: Global Controls ก่อน Notebook
        self.create_global_controls(self.master)
        
        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(pady=5, padx=10, expand=True, fill='both')
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)

        live_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(live_tab, text='🚀 Live Connection')
        self.create_live_widgets(live_tab)

        tts_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tts_tab, text='🎤 Custom TTS')
        self.create_custom_tts_widgets(tts_tab)

        self.create_status_and_log_widgets(self.master)
        
        self.is_custom_tts_active.clear()
        self.update_live_status_periodically()

    def add_context_menu(self, widget):
        menu = Menu(widget, tearoff=0)
        if isinstance(widget, tk.Text):
            menu.add_command(label="Copy", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
            menu.add_command(label="Cut", command=lambda: widget.event_generate("<<Cut>>"))
        else:
            def copy_selected():
                try: widget.clipboard_append(widget.selection_get())
                except: pass
            def paste_clipboard():
                try: widget.insert(tk.INSERT, widget.clipboard_get())
                except: pass
            def cut_selected():
                try: widget.event_generate("<<Cut>>")
                except: pass
            
            menu.add_command(label="Copy", command=copy_selected)
            menu.add_command(label="Paste", command=paste_clipboard)
            menu.add_command(label="Cut", command=cut_selected)
            
        def popup(e): menu.tk_popup(e.x_root, e.y_root)
        widget.bind("<Button-3>", popup)

    def on_tab_change(self, event):
        tab_name = self.notebook.tab(self.notebook.select(), "text")
        if 'Live Connection' in tab_name:
            self.is_custom_tts_active.clear()
            self.log_message("โหมด: Live Connection")
        else:
            self.is_custom_tts_active.set()
            self.log_message("โหมด: Custom TTS")

    def update_live_status_periodically(self):
        self.status_queue_count.set(str(self.tts_queue.qsize()))
        self.status_connection.set("Connected" if self.is_connected else "Disconnected")
        if self.connection_status_label:
            self.connection_status_label.config(foreground="green" if self.is_connected else "red")
        if not self.is_speaking.is_set():
            self.status_speaker.set("-")
            
        # อัปเดตสถิติทุก 500ms
        self.update_realtime_stats()
            
        self.master.after(500, self.update_live_status_periodically)

    def update_realtime_stats(self):
        if self.is_connected:
            duration = time.time() - self.live_start_time
            read_count = self.comments_read_count.get()
            
            if duration > 10 and read_count > 0:
                rate = (read_count / duration) * 60
                self.avg_read_rate.set(f"{rate:.2f} ข้อความ/นาที")
            elif duration > 10 and read_count == 0:
                self.avg_read_rate.set("0.00 ข้อความ/นาที")
            else:
                self.avg_read_rate.set("กำลังคำนวณ...")
        else:
            self.avg_read_rate.set("-")

    # *** ฟังก์ชันแก้ไข: เปิดลิงก์วิดีโอโดยเฉพาะ ***
    def open_tiktok_profile(self):
        video_url = "https://www.tiktok.com/@sontayatongsima/video/7565109859696397576" 
        try:
            webbrowser.open_new_tab(video_url)
            self.log_message("🌐 เปิดลิงก์วิดีโอ TikTok ในเบราว์เซอร์")
        except Exception as e:
            self.log_message(f"❌ ไม่สามารถเปิดเบราว์เซอร์ได้: {e}")

    # *** ฟังก์ชันใหม่: ตรวจสอบอัปเดต ***
    def check_for_updates(self):
        self.log_message("⏳ ตรวจสอบเวอร์ชันล่าสุด...")
        threading.Thread(target=self._run_update_check, daemon=True).start()

    def _run_update_check(self):
        try:
            # 1. ดึงเวอร์ชันล่าสุด
            response = requests.get(UPDATE_CHECK_URL, timeout=10)
            response.raise_for_status()
            remote_version = response.text.strip()
            
            # 2. เปรียบเทียบ
            if remote_version > CURRENT_VERSION:
                self.log_message(f"✅ พบเวอร์ชันใหม่: v{remote_version} (ปัจจุบัน v{CURRENT_VERSION})")
                self.master.after(0, lambda: self._prompt_update(remote_version))
            elif remote_version == CURRENT_VERSION:
                self.log_message(f"✅ โปรแกรมเป็นเวอร์ชันล่าสุดแล้ว (v{CURRENT_VERSION})")
                self.master.after(0, lambda: messagebox.showinfo("Update Check", "โปรแกรมเป็นเวอร์ชันล่าสุดแล้ว"))
            else:
                 self.log_message(f"⚠️ เวอร์ชันรีโมทต่ำกว่า (Remote v{remote_version} < Local v{CURRENT_VERSION})")
                 self.master.after(0, lambda: messagebox.showinfo("Update Check", "โปรแกรมเป็นเวอร์ชันล่าสุดแล้ว"))
                 
        except requests.exceptions.RequestException as e:
            self.log_message(f"❌ ตรวจสอบอัปเดตล้มเหลว: {e}")
            self.master.after(0, lambda: messagebox.showerror("Update Error", f"ไม่สามารถเชื่อมต่อเพื่อตรวจสอบอัปเดตได้: {e}"))
        except Exception as e:
            self.log_message(f"❌ ตรวจสอบอัปเดตล้มเหลว (Unknown): {e}")
            self.master.after(0, lambda: messagebox.showerror("Update Error", f"เกิดข้อผิดพลาดในการตรวจสอบอัปเดต: {e}"))
            
    def _prompt_update(self, remote_version):
        if messagebox.askyesno(
            "Update Available", 
            f"พบเวอร์ชันใหม่ v{remote_version} ต้องการดาวน์โหลดและอัปเดตทันทีหรือไม่?\n\n(โปรแกรมจะปิดตัวลงหลังจากดาวน์โหลดเสร็จสิ้น)"
        ):
            self.log_message("⬇️ เริ่มดาวน์โหลด...")
            # Thread สำหรับการดาวน์โหลด (เพื่อไม่ให้ UI ค้าง)
            threading.Thread(target=self._download_and_install, args=(remote_version,), daemon=True).start()
        else:
            self.log_message("การอัปเดตถูกยกเลิกโดยผู้ใช้")

    def _download_and_install(self, remote_version):
        try:
            # ต้อง Import shutil ในฟังก์ชันนี้เพื่อความปลอดภัย
            import shutil
            
            self.log_message("⬇️ กำลังดาวน์โหลดไฟล์ติดตั้ง...")
            
            # ดาวน์โหลดไฟล์
            response = requests.get(DOWNLOAD_URL, stream=True, timeout=300) 
            response.raise_for_status()
            
            # กำหนดชื่อไฟล์ติดตั้งที่ดาวน์โหลด
            download_path = os.path.join(tempfile.gettempdir(), f"TikTokTTS_v{remote_version}.exe")
            
            with open(download_path, 'wb') as f:
                shutil.copyfileobj(response.raw, f)
            
            self.log_message(f"✅ ดาวน์โหลดเสร็จสิ้น: {download_path}")

            # สั่งให้โปรแกรมปิดตัวลงและรันไฟล์ติดตั้ง (สำหรับ Windows .exe)
            if sys.platform.startswith('win'):
                os.startfile(download_path)
                self.log_message("🚀 เรียกใช้โปรแกรมติดตั้งแล้ว ปิดระบบ...")
                self.master.after(100, lambda: self.perform_shutdown()) # ให้เวลา UI ปิดตัวก่อน
            else:
                self.log_message("✅ อัปเดตพร้อมใช้งาน กรุณาติดตั้งด้วยตนเอง")
                self.master.after(0, lambda: messagebox.showinfo("Download Complete", 
                                f"ดาวน์โหลด v{remote_version} เสร็จสิ้น\nกรุณาปิดโปรแกรมและติดตั้งด้วยตนเอง"))
                
        except requests.exceptions.RequestException as e:
            self.log_message(f"❌ ดาวน์โหลดล้มเหลว: {e}")
            self.master.after(0, lambda: messagebox.showerror("Download Error", f"ดาวน์โหลดไม่สำเร็จ: {e}"))
        except Exception as e:
            self.log_message(f"❌ เกิดข้อผิดพลาดในการติดตั้ง: {e}")
            self.master.after(0, lambda: messagebox.showerror("Download Error", f"เกิดข้อผิดพลาดในการอัปเดต: {e}"))


    def create_menu_bar(self):
        menubar = tk.Menu(self.master)
        self.master.config(menu=menubar)
        
        # เมนู About (ใหม่)
        menubar.add_command(label="About", command=self.open_tiktok_profile)

        # เมนู Help (เดิม)
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="วิธีใช้", command=self.show_help)
        # *** เพิ่ม: ปุ่มตรวจสอบอัปเดต ***
        help_menu.add_command(label="Check for Updates", command=self.check_for_updates) 

    def show_help(self):
        messagebox.showinfo("วิธีใช้", 
            "1. เลือกเสียง (ผู้ชาย = Achara)\n"
            "2. ปรับ Pitch (ความทุ้ม/แหลม) และ Speed\n"
            "3. ทดสอบใน Custom TTS ก่อน\n"
            "4. ใส่ชื่อ TikTok > Connect ในแท็บ Live\n"
            "5. 'Skip Comment' เพื่อข้ามข้อความที่กำลังพูดอยู่ และอ่านข้อความที่เข้าคิวล่าสุดแทน\n"
            "6. 'Pause TTS' เพื่อหยุดการอ่านชั่วคราวขณะที่ยังเชื่อมต่อ Live อยู่\n"
            "7. 'Open Live Video' เพื่อเปิดหน้า Live สดในเบราว์เซอร์\n"
            "8. 'Clear Text' เพื่อล้างข้อความใน Custom TTS\n\n"
            "มี 2 เสียงหลัก: Premwadee (หญิง), Achara (ชาย)")

    def perform_shutdown(self):
        self.log_message("ปิดระบบ...")
        with self.tts_queue.mutex: self.tts_queue.queue.clear()
        self.tts_queue.put(None)
        self.tts_thread.join(timeout=1)
        if self.client: 
            try: self.client.disconnect()
            except: pass
        if self.tray_icon: self.tray_icon.stop()
        pygame.mixer.quit()
        os._exit(0) 

    def on_window_close(self):
        if messagebox.askyesno("ออก", "ต้องการออกจากโปรแกรม?"):
            threading.Thread(target=self.perform_shutdown, daemon=True).start()
        else:
            self.master.iconify()

    def on_minimize(self, event):
        if self.master.state() == 'iconic':
            self.master.withdraw()
            self.create_tray_icon()

    def create_tray_icon(self):
        if self.tray_icon: return
        try: image = Image.open(resource_path("tray_icon.png"))
        except: 
            image = Image.new('RGB', (64,64), 'blue')
            d = ImageDraw.Draw(image)
            d.text((10,10), "TTS", fill="white")
        menu = (pystray.MenuItem('แสดง', self.show_window), pystray.MenuItem('ออก', self.exit_application))
        self.tray_icon = pystray.Icon("tts", image, "TikTok TTS", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon=None, item=None):
        if icon: icon.stop()
        self.tray_icon = None
        self.master.deiconify()
        self.master.lift()

    def exit_application(self, icon, item):
        threading.Thread(target=self.perform_shutdown, daemon=True).start()

    def create_global_controls(self, container):
        # 3. Global Controls - จัดให้อยู่เหนือ Notebook และใช้พื้นที่แนวนอนเต็มที่
        ctrl = ttk.Frame(container, padding="10 5 10 5", relief='groove', borderwidth=1); ctrl.pack(fill='x')

        # Voice (ซ้าย)
        ttk.Label(ctrl, text="🗣️ เสียง:").pack(side='left', padx=(5,2))
        voice_cb = ttk.Combobox(ctrl, textvariable=self.voice_id, 
                                values=[v for _,v in self.VOICE_OPTIONS], 
                                state="readonly", width=20) 
        voice_cb.pack(side='left', padx=5)
        voice_cb.set("th-TH-AcharaNeural")

        # Pitch (กลาง)
        ttk.Label(ctrl, text="Pitch (Hz):").pack(side='left', padx=(10,2))
        pitch_cb = ttk.Combobox(ctrl, textvariable=self.pitch_shift, 
                                values=[n for n,_ in self.PITCH_OPTIONS], 
                                state="readonly", width=4)
        pitch_cb.pack(side='left', padx=5)
        pitch_cb.set("0")

        # Speed (กลาง)
        ttk.Label(ctrl, text="Speed:").pack(side='left', padx=(10,2))
        speed_cb = ttk.Combobox(ctrl, textvariable=self.speed_rate, 
                                values=[n for n,_ in self.SPEED_OPTIONS], 
                                state="readonly", width=4)
        speed_cb.pack(side='left', padx=5)
        speed_cb.set("1.0")
        
        pass 

    # *** ฟังก์ชันสำหรับ Live Control ***
    def toggle_tts_pause(self):
        if self.is_tts_paused.get():
            self.is_tts_paused.set(False)
            self.log_message("▶️ TTS กลับมาทำงานต่อ (Queue Resume)")
            self.pause_button.config(text="⏸️ Pause TTS")
        else:
            self.is_tts_paused.set(True)
            self.log_message("⏸️ TTS ถูกพักการทำงาน (Queue Paused)")
            self.pause_button.config(text="▶️ Resume TTS")

    def skip_comment(self):
        if self.is_speaking.is_set():
            pygame.mixer.music.stop()
            self.log_message("🛑 หยุดพูดปัจจุบัน")

        if self.last_comment_for_skip and self.tts_queue.qsize() > 0:
            with self.tts_queue.mutex: self.tts_queue.queue.clear()
            self.tts_queue.put(self.last_comment_for_skip) 
            self.last_comment_for_skip = None
            self.log_message("⏩ ข้ามคิว อ่านข้อความล่าสุด")
        elif self.tts_queue.qsize() > 0:
            with self.tts_queue.mutex: self.tts_queue.queue.clear()
            self.last_comment_for_skip = None
            self.log_message("⏩ เคลียร์คิวทั้งหมด")
        else:
            self.log_message("❌ ไม่มีคอมเมนต์ในคิวที่จะข้ามได้")

    def open_live_in_browser(self):
        username = self.username_entry.get().strip()
        if not username:
            messagebox.showerror("Error", "กรุณากรอกชื่อ TikTok Username ก่อน")
            return
            
        live_url = f"https://www.tiktok.com/@{username}/live"
        try:
            webbrowser.open_new_tab(live_url)
            self.log_message(f"🌐 เปิด Live ของ @{username} ในเบราว์เซอร์ (เบื้องหลัง)")
        except Exception as e:
            self.log_message(f"❌ ไม่สามารถเปิดเบราว์เซอร์ได้: {e}")

    def create_live_widgets(self, container):
        # 1. Username & Connect
        f = ttk.Frame(container); f.pack(fill='x', pady=5)
        ttk.Label(f, text="TikTok Username:").pack(side='left', padx=5)
        self.username_entry = ttk.Entry(f, width=25) 
        self.username_entry.pack(side='left', padx=5, expand=True, fill='x')
        self.username_entry.insert(0, "sontayatongsima")
        self.connect_button = ttk.Button(f, text="Connect", command=self.toggle_connection)
        self.connect_button.pack(side='left', padx=5)
        self.add_context_menu(self.username_entry)

        # 2. สถานะ (Status) - ใช้ Grid เพื่อลดพื้นที่แนวตั้งและจัดให้สมดุล
        status = ttk.LabelFrame(container, text="📊 สถานะ", padding=10); status.pack(fill='x', pady=10)
        
        # Row 0: Connection & Queue
        ttk.Label(status, text="สถานะการเชื่อมต่อ:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        self.connection_status_label = ttk.Label(status, textvariable=self.status_connection, font=('',10,'bold')); 
        self.connection_status_label.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        
        ttk.Label(status, text="คิวข้อความ:").grid(row=0, column=2, sticky='e', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_queue_count, font=('',9,'bold')).grid(row=0, column=3, sticky='w', padx=5, pady=2)
        
        # Row 1: Speaker
        ttk.Label(status, text="กำลังอ่าน:").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_speaker, foreground="blue", font=('',9,'bold')).grid(row=1, column=1, columnspan=3, sticky='w', padx=5, pady=2)

        # เพิ่มการขยายของคอลัมน์ 1 และ 3 เพื่อกระจายพื้นที่
        status.columnconfigure(1, weight=1)
        status.columnconfigure(3, weight=1)

        # *** 3. Live Control (ปุ่มควบคุม) ***
        ctrl_frame = ttk.LabelFrame(container, text="🛠️ Live Control", padding=10)
        ctrl_frame.pack(fill='x', pady=10)

        # ใช้ Grid จัดเรียงปุ่ม
        ctrl_frame.columnconfigure(0, weight=1)
        ctrl_frame.columnconfigure(1, weight=1)

        # Row 0: Pause และ Skip
        self.pause_button = ttk.Button(ctrl_frame, text="⏸️ Pause TTS", command=self.toggle_tts_pause)
        self.pause_button.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        ttk.Button(ctrl_frame, text="⏩ Skip Comment", command=self.skip_comment).grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        
        # Row 1: Open Live
        ttk.Button(ctrl_frame, text="🌐 Open Live Video", command=self.open_live_in_browser).grid(row=1, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        
        # Row 2: สรุปเสียงปัจจุบัน
        ttk.Label(ctrl_frame, text="Current Voice:").grid(row=2, column=0, sticky='w', padx=5, pady=2)
        
        voice_summary = tk.StringVar()
        def update_voice_summary():
            v_name = next((name for name, id in self.VOICE_OPTIONS if id == self.voice_id.get()), self.voice_id.get())
            display_name = v_name.split(' - ')[0] 
            
            p_val = self.pitch_shift.get()
            s_val = self.speed_rate.get()
            voice_summary.set(f"{display_name} | Pitch: {p_val:+d}Hz | Speed: {s_val:.2f}x")
            self.master.after(1000, update_voice_summary) 
        
        ttk.Label(ctrl_frame, textvariable=voice_summary, foreground='blue', font=('', 9, 'bold')).grid(row=2, column=1, sticky='w', padx=5, pady=2)
        update_voice_summary()
        
        # ตัวยึดพื้นที่ที่เหลือในแท็บ Live (ถ้ามี)
        ttk.Frame(container).pack(fill='both', expand=True)

    # *** ฟังก์ชัน: ล้างข้อความ Custom TTS ***
    def clear_custom_text(self):
        self.tts_text_entry.delete("1.0", tk.END)
        self.download_button.config(state='disabled')
        self.last_generated_file = None
        self.log_message("🎤 ล้างข้อความ Custom TTS แล้ว")

    def create_custom_tts_widgets(self, container):
        # 4. Custom TTS - Text Area ใช้พื้นที่แนวตั้งที่เหลือทั้งหมด
        ttk.Label(container, text="📝 ข้อความที่ต้องการอ่าน:").pack(anchor='w', pady=(0,5))
        self.tts_text_entry = tk.Text(container, height=10, wrap='word') # เพิ่มความสูงเริ่มต้น
        self.tts_text_entry.pack(fill='both', expand=True, pady=5)
        self.add_context_menu(self.tts_text_entry)

        btns = ttk.Frame(container); btns.pack(fill='x', pady=5)
        
        # จัดเรียงปุ่มเป็น 3 คอลัมน์
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        btns.columnconfigure(2, weight=1)
        
        ttk.Button(btns, text="🔊 Preview", command=self.generate_and_preview_tts).grid(row=0, column=0, sticky='ew', padx=5)
        self.download_button = ttk.Button(btns, text="⬇️ Download MP3", command=self.download_tts_file, state='disabled')
        self.download_button.grid(row=0, column=1, sticky='ew', padx=5)
        
        # *** ปุ่ม Clear Text ***
        ttk.Button(btns, text="🗑️ Clear Text", command=self.clear_custom_text).grid(row=0, column=2, sticky='ew', padx=5)

    def create_status_and_log_widgets(self, container):
        # *** 5. Real-time Statistics Area ***
        statsf = ttk.LabelFrame(container, text="📈 สถิติ Live", padding=10); statsf.pack(fill='x', expand=False, padx=10, pady=(5, 5))
        
        # ใช้ Grid สำหรับจัดเรียงสถิติ 2 แถว 3 คอลัมน์
        statsf.columnconfigure(1, weight=1)
        statsf.columnconfigure(3, weight=1)
        statsf.columnconfigure(5, weight=1)

        # Row 0
        ttk.Label(statsf, text="🗣️ อ่านแล้ว:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(statsf, textvariable=self.comments_read_count, font=('',9,'bold')).grid(row=0, column=1, sticky='w', padx=5, pady=2)

        ttk.Label(statsf, text="🗑️ ถูกกรอง:").grid(row=0, column=2, sticky='w', padx=10, pady=2)
        ttk.Label(statsf, textvariable=self.comments_filtered_count, font=('',9,'bold')).grid(row=0, column=3, sticky='w', padx=5, pady=2)
        
        ttk.Label(statsf, text="⏱️ อัตราอ่าน:").grid(row=0, column=4, sticky='w', padx=10, pady=2)
        ttk.Label(statsf, textvariable=self.avg_read_rate, font=('',9,'bold'), foreground='darkgreen').grid(row=0, column=5, sticky='w', padx=5, pady=2)

        # 6. Log Area - อยู่ล่างสุดและมีขนาดคงที่
        logf = ttk.LabelFrame(container, text="📜 Log", padding=10); logf.pack(fill='x', expand=False, padx=10, pady=(0, 10))
        self.log_text = tk.Text(logf, height=6, state='disabled'); self.log_text.pack(fill='both', expand=True) # ปรับความสูงให้สมดุล
        sb = ttk.Scrollbar(logf, command=self.log_text.yview); sb.pack(side='right', fill='y')
        self.log_text['yscrollcommand'] = sb.set
        self.add_context_menu(self.log_text)

    # -----------------------------------------------------------------
    # TTS Functions
    # -----------------------------------------------------------------
    async def _generate_tts_async(self, text, output_file):
        if not text.strip():
            raise ValueError("ข้อความว่างเปล่า")

        rate_val = self.speed_rate.get()
        pitch_val = self.pitch_shift.get()

        # แปลง Rate เป็น string format
        if abs(rate_val - 1.0) < 1e-6:
            rate_str = None
        else:
            rate_pct = int((rate_val - 1.0) * 100)
            rate_str = f"{rate_pct:+}%"

        # แปลง Pitch เป็น string format
        if pitch_val == 0:
            pitch_str = None
        else:
            # edge-tts ใช้ +5Hz/-5Hz เป็นหน่วย
            pitch_str = f"{pitch_val:+}Hz" 

        kwargs = {
            "text": text,
            "voice": self.voice_id.get(),
        }
        if rate_str:
            kwargs["rate"] = rate_str
        if pitch_str:
            kwargs["pitch"] = pitch_str

        communicate = edge_tts.Communicate(**kwargs)
        await communicate.save(output_file)

    def _process_custom_tts(self, text):
        self.is_generating_tts.set()
        temp_file = os.path.join(tempfile.gettempdir(), f"custom_temp_{uuid.uuid4()}.mp3")
        final_file = os.path.join(tempfile.gettempdir(), f"custom_final_{uuid.uuid4()}.mp3")

        try:
            self.log_message("กำลังสร้างเสียง Custom TTS...")
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            loop.run_until_complete(self._generate_tts_async(text, temp_file))
            
            if not os.path.exists(temp_file) or os.path.getsize(temp_file) == 0:
                raise Exception("ไฟล์เสียงว่างเปล่า หรือเกิดข้อผิดพลาดในการสร้างไฟล์")

            import shutil
            shutil.copyfile(temp_file, final_file)

            self.log_message("กำลังเล่นเสียง...")
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
            pygame.mixer.music.unload() 

            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except Exception as e: self.log_message(f"Custom TTS Warning: ไม่สามารถลบไฟล์ชั่วคราวได้: {e}")

            self.last_generated_file = final_file
            self.master.after(0, lambda: self.download_button.config(state='normal'))
            self.log_message("Custom TTS สำเร็จ! พร้อมดาวน์โหลด")

        except Exception as e:
            self.log_message(f"Custom TTS Error: {e}")
            self.master.after(0, lambda: self.download_button.config(state='disabled'))
        finally:
            self.is_generating_tts.clear()
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

    def generate_and_preview_tts(self):
        text = self.tts_text_entry.get("1.0", tk.END).strip()
        if not text:
            messagebox.showerror("Error", "กรุณากรอกข้อความ")
            return
        if self.is_generating_tts.is_set():
            messagebox.showinfo("รอ", "กำลังสร้างเสียง... กรุณารอสักครู่")
            return
        if self.is_connected and self.tts_queue.qsize() > 0:
             messagebox.showerror("Error", "มีคิว Live Connection อยู่, กรุณารอให้คิวหมดก่อน")
             return
             
        self.download_button.config(state='disabled')
        threading.Thread(target=self._process_custom_tts, args=(text,), daemon=True).start()

    def download_tts_file(self):
        if not self.last_generated_file or not os.path.exists(self.last_generated_file):
            messagebox.showerror("Error", "ไม่มีไฟล์ให้ดาวน์โหลด")
            return
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3 files", "*.mp3")],
            initialfile=f"tts_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
        )
        if path:
            import shutil
            shutil.copyfile(self.last_generated_file, path)
            try: os.remove(self.last_generated_file)
            except: pass
            self.last_generated_file = None
            self.download_button.config(state='disabled')
            messagebox.showinfo("สำเร็จ", f"บันทึกที่:\n{path}")

    # -----------------------------------------------------------------
    # Live Connection
    # -----------------------------------------------------------------
    def log_message(self, msg):
        def _insert_log():
            with self.log_lock:
                self.log_text.config(state='normal')
                self.log_text.insert('end', f"{time.strftime('%H:%M:%S')} {msg}\n")
                self.log_text.see('end')
                self.log_text.config(state='disabled')
        self.master.after(0, _insert_log)

    def toggle_connection(self):
        if not self.is_connected:
            if self.is_custom_tts_active.is_set():
                messagebox.showerror("Error", "สลับไปแท็บ Live Connection ก่อน")
                return
            user = self.username_entry.get().strip()
            if not user:
                messagebox.showerror("Error", "กรอกชื่อ TikTok Username")
                return
            self.username_entry.config(state='disabled')
            self.connect_button.config(text="Connecting...", state='disabled')
            threading.Thread(target=self.start_client, args=(user,), daemon=True).start()
        else:
            self.stop_client()

    def start_client(self, username):
        try:
            self.client = TikTokLiveClient(username)
            self.client.headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
                "Referer": f"https://www.tiktok.com/@{username}/live"
            }
            self.client.on(CommentEvent)(self.on_comment)
            self.client.on(ConnectEvent)(self.on_connect_success)
            self.client.on(DisconnectEvent)(self.on_disconnect)
            self.client.run()
        except Exception as e:
            self.log_message(f"❌ เชื่อมต่อล้มเหลว: {e}")
            self.master.after(0, self.update_gui_after_disconnect)

    def stop_client(self):
        if self.client:
            self.log_message("⏳ กำลังตัดการเชื่อมต่อ...")
            with self.tts_queue.mutex: self.tts_queue.queue.clear()
            threading.Thread(target=self.client.disconnect, daemon=True).start()
            self.is_connected = False
            self.master.after(0, self.update_gui_after_disconnect)

    def update_gui_after_disconnect(self):
        self.is_connected = False
        self.client = None
        self.username_entry.config(state='normal')
        self.connect_button.config(text="Connect", state='normal')
        self.log_message("🔌 ตัดการเชื่อมต่อแล้ว")
        self.status_speaker.set("-")
        self.comments_read_count.set(0)
        self.comments_filtered_count.set(0)
        self.avg_read_rate.set("-")
        self.is_tts_paused.set(False)

    async def on_comment(self, event: CommentEvent): # <--- CommentEvent ถูกเรียกใช้
        if not self.is_connected or self.is_custom_tts_active.is_set(): 
            return
            
        user = event.user.nickname
        comment = event.comment.strip()
        
        if not comment: return
        
        if len(comment) < 1 or len(comment) > 200: 
            self.log_message(f"🗑️ {user}: คอมเมนต์ถูกกรอง (ความยาว: {len(comment)})")
            self.master.after(0, lambda: self.comments_filtered_count.set(self.comments_filtered_count.get() + 1))
            return
        
        self.log_message(f"💬 {user}: {comment}")
        tts_text = f"{user} พูดว่า {comment}"
        self.last_comment_for_skip = tts_text 
        
        self.speak_async(tts_text)

    async def on_connect_success(self, event: ConnectEvent):
        self.master.after(0, lambda: self.connect_button.config(text="Disconnect", state='normal'))
        self.is_connected = True
        self.live_start_time = time.time()
        self.log_message(f"✅ เชื่อมต่อ @{self.client.unique_id} สำเร็จ!")
        self.speak_async("เชื่อมต่อสำเร็จ")

    async def on_disconnect(self, event: DisconnectEvent):
        self.log_message("⚠️ หลุดการเชื่อมต่อ")
        self.master.after(0, self.update_gui_after_disconnect)

    # -----------------------------------------------------------------
    # TTS Worker
    # -----------------------------------------------------------------
    def tts_worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while True:
            text = self.tts_queue.get()
            if text is None: break
            
            if self.is_tts_paused.get():
                self.tts_queue.put(text)
                time.sleep(0.5)
                continue
            
            if self.is_custom_tts_active.is_set() or not self.is_connected:
                self.tts_queue.task_done()
                continue

            self.is_speaking.set()
            temp_file = os.path.join(tempfile.gettempdir(), f"live_{uuid.uuid4()}.mp3")
            try:
                self.log_message(f"🎧 กำลังสร้างเสียง: {text.split(' พูดว่า ')[1][:30]}...")
                loop.run_until_complete(self._generate_tts_async(text, temp_file))
                
                if not os.path.exists(temp_file) or os.path.getsize(temp_file) == 0:
                    raise Exception("ไฟล์เสียงว่างเปล่า")

                speaker = text.split(" พูดว่า ")[0]
                self.master.after(0, lambda n=speaker: self.status_speaker.set(n))
                pygame.mixer.music.load(temp_file)
                pygame.mixer.music.play()
                
                while pygame.mixer.music.get_busy():
                    if not self.is_connected:
                        pygame.mixer.music.stop()
                        break
                    time.sleep(0.1)
                
                pygame.mixer.music.unload() 
                
                self.master.after(0, lambda: self.comments_read_count.set(self.comments_read_count.get() + 1))
                    
            except Exception as e:
                self.log_message(f"TTS Worker Error: {e}")
            finally:
                self.is_speaking.clear()
                self.master.after(0, lambda: self.status_speaker.set("-"))
                
                if os.path.exists(temp_file):
                    try: 
                        os.remove(temp_file)
                    except Exception as e:
                        self.log_message(f"TTS Worker Warning: ลบไฟล์ไม่สำเร็จ: {temp_file} | {e}") 

                self.tts_queue.task_done()
                
        loop.close()

    def speak_async(self, text):
        self.tts_queue.put(text)

# =======================================================
# Run
# =======================================================
if __name__ == '__main__':
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
        
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use('clam')
    except:
        pass
        
    app = TikTokTTSApp(root)
    root.mainloop()


