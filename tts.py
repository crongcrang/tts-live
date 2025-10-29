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
import tqdm 
import urllib.parse 

# TikTok Live
from TikTokLive import TikTokLiveClient
from TikTokLive import events 

# Twitch (ยังต้อง Import เพื่อรองรับ Type ที่อาจถูกเรียกใช้ แต่จะเปลี่ยน Logic การเชื่อมต่อ)
from twitchAPI.twitch import Twitch
from twitchAPI.chat import Chat, ChatMessage
from twitchAPI.type import AuthScope
# *** เพิ่ม: สำหรับ Direct IRC Connection ***
import irc.bot 
# *****************************************

# *** เพิ่ม: สำหรับ YouTube Live Chat ***
import pytchat
import pytchat.exceptions
# ***********************************

# edge-tts
import edge_tts

# =======================================================
# 0. Resource Path & Global Config
# =======================================================

# หมายเลขเวอร์ชันปัจจุบันของโปรแกรม
CURRENT_VERSION = "1.0.2" 
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
        master.title(f"TTS Live v{CURRENT_VERSION}") 
        master.geometry("620x780") 
        
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
        
        # *** เพิ่ม Event สำหรับส่งสัญญาณว่า TTS Worker หยุดพูดแล้ว ***
        self.speech_stopped_event = threading.Event()

        # สถานะการเชื่อมต่อและคิว
        self.status_connection = tk.StringVar(value="Disconnected")
        self.status_speaker = tk.StringVar(value="-")
        self.status_queue_count = tk.StringVar(value="0")
        self.connection_status_label = None
        
        # *** ตัวแปรสำหรับปุ่ม Pause TTS ในแต่ละแท็บ ***
        self.pause_button = None # TikTok (ปุ่มหลัก)
        self.pause_button_twitch = None 
        self.pause_button_youtube = None
        
        # *** ตัวแปรสำหรับ Voice Summary ในแต่ละแท็บ ***
        self.voice_summary_tiktok = tk.StringVar()
        self.voice_summary_twitch = tk.StringVar()
        self.voice_summary_youtube = tk.StringVar()
        # **********************************************

        # *** ตัวแปรสำหรับ Twitch ***
        self.twitch_client = None
        self.twitch_api = None 
        self.is_twitch_connected = False
        self.twitch_chat_thread = None
        self.status_twitch_connection = tk.StringVar(value="Disconnected")
        
        self.twitch_oauth_token_entry = None 
        self.twitch_bot_username_entry = None 
        self.twitch_channel_entry = None
        self.twitch_connect_button = None
        self.twitch_status_label_indicator = None 
        
        self.twitch_id_entry = None
        self.twitch_secret_entry = None
        # *****************************************

        # *** ตัวแปรสำหรับ YouTube ***
        self.youtube_chat = None
        self.youtube_chat_thread = None
        self.is_youtube_connected = False
        self.status_youtube_connection = tk.StringVar(value="Disconnected")
        self.youtube_video_id_entry = None
        self.youtube_connect_button = None
        self.youtube_status_label_indicator = None
        # ***************************

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
        self.notebook.add(live_tab, text='🚀 Live Connection (TikTok)')
        self.create_live_widgets(live_tab)

        # *** เพิ่มแท็บ Twitch ***
        twitch_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(twitch_tab, text='🟣 Live Chat (Twitch)')
        self.create_twitch_widgets(twitch_tab)
        # ***********************
        
        # *** เพิ่มแท็บ YouTube ***
        youtube_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(youtube_tab, text='🔴 Live Chat (YouTube)')
        self.create_youtube_widgets(youtube_tab)
        # *************************

        tts_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tts_tab, text='🎤 Custom TTS')
        self.create_custom_tts_widgets(tts_tab)

        self.create_status_and_log_widgets(self.master)
        
        self.is_custom_tts_active.clear()
        self.update_voice_summary_periodically() # เริ่มอัปเดต Voice Summary
        self.update_live_status_periodically()

    def add_context_menu(self, widget):
        """เพิ่มฟังก์ชันคลิกขวา Copy/Paste/Cut"""
        menu = Menu(widget, tearoff=0)
        
        if isinstance(widget, tk.Text):
            # สำหรับ tk.Text
            menu.add_command(label="Cut", command=lambda: widget.event_generate("<<Cut>>"))
            menu.add_command(label="Copy", command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="Paste", command=lambda: widget.event_generate("<<Paste>>"))
        else:
            # สำหรับ ttk.Entry หรือ ttk.Combobox
            def copy_selected():
                try: widget.clipboard_append(widget.selection_get())
                except: pass
            def paste_clipboard():
                try: widget.insert(tk.INSERT, widget.clipboard_get())
                except: pass
            def cut_selected():
                try: widget.event_generate("<<Cut>>")
                except: pass
            
            menu.add_command(label="Cut", command=cut_selected)
            menu.add_command(label="Copy", command=copy_selected)
            menu.add_command(label="Paste", command=paste_clipboard)
            
        def popup(e): menu.tk_popup(e.x_root, e.y_root)
        widget.bind("<Button-3>", popup) # ผูกกับคลิกขวา
        widget.bind("<Control-c>", lambda e: widget.event_generate("<<Copy>>"))
        widget.bind("<Control-v>", lambda e: widget.event_generate("<<Paste>>"))
        widget.bind("<Control-x>", lambda e: widget.event_generate("<<Cut>>"))


    def on_tab_change(self, event):
        tab_name = self.notebook.tab(self.notebook.select(), "text")
        if 'TikTok' in tab_name:
            self.is_custom_tts_active.clear()
            self.log_message("โหมด: TikTok Live Connection")
        elif 'Twitch' in tab_name:
            self.is_custom_tts_active.clear()
            self.log_message("โหมด: Twitch Live Chat")
        elif 'YouTube' in tab_name:
            self.is_custom_tts_active.clear()
            self.log_message("โหมด: YouTube Live Chat")
        else:
            self.is_custom_tts_active.set()
            self.log_message("โหมด: Custom TTS")

    def update_voice_summary_periodically(self):
        """อัปเดต Voice Summary ในทุกตัวแปรที่เกี่ยวข้อง"""
        v_name = next((name for name, id in self.VOICE_OPTIONS if id == self.voice_id.get()), self.voice_id.get())
        display_name = v_name.split(' - ')[0] 
        
        p_val = self.pitch_shift.get()
        s_val = self.speed_rate.get()
        summary = f"{display_name} | Pitch: {p_val:+d}Hz | Speed: {s_val:.2f}x"
        
        self.voice_summary_tiktok.set(summary)
        self.voice_summary_twitch.set(summary)
        self.voice_summary_youtube.set(summary)
        
        self.master.after(1000, self.update_voice_summary_periodically) 


    def update_live_status_periodically(self):
        self.status_queue_count.set(str(self.tts_queue.qsize()))
        
        # อัปเดตสถานะการเชื่อมต่อรวม
        is_any_connected = self.is_connected or self.is_twitch_connected or self.is_youtube_connected
        self.status_connection.set("Connected" if is_any_connected else "Disconnected")
        if self.connection_status_label:
            self.connection_status_label.config(foreground="green" if is_any_connected else "red")
        
        if self.twitch_status_label_indicator:
             self.twitch_status_label_indicator.config(foreground="green" if self.is_twitch_connected else "red")
             
        if self.youtube_status_label_indicator:
             self.youtube_status_label_indicator.config(foreground="green" if self.is_youtube_connected else "red")
             
        if not self.is_speaking.is_set():
            self.status_speaker.set("-")
            
        # อัปเดตสถิติทุก 500ms
        self.update_realtime_stats()
            
        self.master.after(500, self.update_live_status_periodically)

    def update_realtime_stats(self):
        if self.is_connected or self.is_twitch_connected or self.is_youtube_connected:
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

    # *** ฟังก์ชัน: เปิดลิงก์วิดีโอ ***
    def open_tiktok_profile(self):
        video_url = "https://www.tiktok.com/@sontayatongsima" 
        try:
            webbrowser.open_new_tab(video_url)
            self.log_message("🌐 เปิดลิงก์วิดีโอ TikTok ในเบราว์เซอร์")
        except Exception as e:
            self.log_message(f"❌ ไม่สามารถเปิดเบราว์เซอร์ได้: {e}")
            
    def open_twitch_channel(self):
        channel = self.twitch_channel_entry.get().strip()
        if not channel:
            messagebox.showerror("Error", "กรุณากรอกชื่อ Twitch Channel ก่อน")
            return
            
        live_url = f"https://www.twitch.tv/{channel}"
        try:
            webbrowser.open_new_tab(live_url)
            self.log_message(f"🌐 เปิด Twitch Channel #{channel} ในเบราว์เซอร์")
        except Exception as e:
            self.log_message(f"❌ ไม่สามารถเปิดเบราว์เซอร์ได้: {e}")
            
    def open_youtube_video(self):
        video_id = self.youtube_video_id_entry.get().strip()
        if not video_id:
            messagebox.showerror("Error", "กรุณากรอก YouTube Video ID ก่อน")
            return
            
        # แยก Video ID ออกจาก URL เต็ม
        if "v=" in video_id:
            try:
                parsed = urllib.parse.urlparse(video_id)
                video_id = urllib.parse.parse_qs(parsed.query).get('v', [video_id])[0]
            except:
                pass 

        live_url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            webbrowser.open_new_tab(live_url)
            self.log_message(f"🌐 เปิด YouTube Video ID: {video_id} ในเบราว์เซอร์")
        except Exception as e:
            self.log_message(f"❌ ไม่สามารถเปิดเบราว์เซอร์ได้: {e}")


    # *** ฟังก์ชัน: ตรวจสอบอัปเดต ***
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
        # *** เปลี่ยนข้อความแจ้งเตือนให้ชัดเจนขึ้น ***
        if messagebox.askyesno(
            "Update Available", 
            f"พบเวอร์ชันใหม่ v{remote_version} ต้องการดาวน์โหลดและบันทึกไฟล์ติดตั้งหรือไม่?\n\n(คุณต้องปิดโปรแกรมและติดตั้งทับไฟล์เดิมด้วยตนเอง)"
        ):
            self.log_message("⬇️ เริ่มดาวน์โหลด...")
            threading.Thread(target=self._download_and_install, args=(remote_version,), daemon=True).start()
        else:
            self.log_message("การอัปเดตถูกยกเลิกโดยผู้ใช้")

    def _download_and_install(self, remote_version):
        try:
            # ต้อง Import shutil ในฟังก์ชันนี้เพื่อความปลอดภัย
            import shutil
            
            self.log_message("⬇️ กำลังดาวน์โหลดไฟล์ติดตั้ง...")
            
            response = requests.get(DOWNLOAD_URL, stream=True, timeout=300) 
            response.raise_for_status()
            
            # 1. กำหนดพาธดาวน์โหลด: Home Directory -> Downloads (ถ้ามี)
            home_dir = os.path.expanduser('~')
            download_dir = os.path.join(home_dir, 'Downloads')
            
            # Fallback หากไม่มีโฟลเดอร์ Downloads (ไม่น่าเกิดขึ้นใน Windows ปกติ)
            if not os.path.isdir(download_dir):
                download_dir = os.path.join(home_dir, 'Desktop')
            
            # 2. กำหนดชื่อไฟล์ติดตั้งที่ดาวน์โหลด
            download_path = os.path.join(download_dir, f"TikTokTTS_v{remote_version}.exe")
            
            with open(download_path, 'wb') as f:
                shutil.copyfileobj(response.raw, f)
            
            self.log_message(f"✅ ดาวน์โหลดเสร็จสิ้น: {download_path}")

            # 3. แจ้งเตือนผู้ใช้ให้ดำเนินการติดตั้ง
            messagebox.showinfo(
                "อัปเดตสำเร็จ", 
                f"ดาวน์โหลดเวอร์ชัน v{remote_version} เสร็จสิ้นแล้ว\n\n"
                f"ไฟล์ถูกบันทึกที่:\n{download_path}\n\n"
                f"กรุณาปิดโปรแกรมนี้, เปิดไฟล์ที่ดาวน์โหลดมา, และติดตั้งทับไฟล์เดิมด้วยตนเอง"
            )
            
            # 4. เสนอให้ปิดโปรแกรม
            if messagebox.askyesno("ปิดโปรแกรม", "ต้องการปิดโปรแกรมนี้ทันทีเพื่อเริ่มติดตั้งหรือไม่?"):
                self.master.after(100, lambda: self.perform_shutdown())
                
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
            "4. แท็บ Live Connection (TikTok): ใส่ชื่อ TikTok > Connect\n"
            "5. แท็บ Live Chat (Twitch): กรอก Channel Name, OAuth Token, Bot Username และ Client ID/Secret จริง > Connect\n"
            "6. แท็บ Live Chat (YouTube): ใส่ Video ID/URL > Connect\n"
            "7. 'Skip Comment' เพื่อข้ามข้อความที่กำลังพูดอยู่ และอ่านข้อความที่เข้าคิวล่าสุดแทน\n"
            "8. 'Pause TTS' เพื่อหยุดการอ่านชั่วคราวขณะที่ยังเชื่อมต่อ Live อยู่\n"
            "9. 'Open Live Video'/'Open Twitch Channel'/'Open YouTube Video' เพื่อเปิดหน้า Live สดในเบราว์เซอร์\n"
            "10. 'Clear Text' เพื่อล้างข้อความใน Custom TTS\n\n"
            "มี 2 เสียงหลัก: Premwadee (หญิง), Achara (ชาย)")

    def perform_shutdown(self):
        self.log_message("ปิดระบบ...")
        with self.tts_queue.mutex: self.tts_queue.queue.clear()
        self.tts_queue.put(None)
        self.tts_thread.join(timeout=1)
        if self.client: 
            try: self.client.disconnect()
            except: pass
        if self.twitch_client:
             try: self.stop_twitch_client()
             except: pass
        if self.youtube_chat:
             try: self.stop_youtube_client()
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
        self.add_context_menu(voice_cb) # เพิ่มเมนูคลิกขวา
        voice_cb.set("th-TH-AcharaNeural")

        # Pitch (กลาง)
        ttk.Label(ctrl, text="Pitch (Hz):").pack(side='left', padx=(10,2))
        pitch_cb = ttk.Combobox(ctrl, textvariable=self.pitch_shift, 
                                values=[n for n,_ in self.PITCH_OPTIONS], 
                                state="readonly", width=4)
        pitch_cb.pack(side='left', padx=5)
        self.add_context_menu(pitch_cb) # เพิ่มเมนูคลิกขวา
        pitch_cb.set("0")

        # Speed (กลาง)
        ttk.Label(ctrl, text="Speed:").pack(side='left', padx=(10,2))
        speed_cb = ttk.Combobox(ctrl, textvariable=self.speed_rate, 
                                values=[n for n,_ in self.SPEED_OPTIONS], 
                                state="readonly", width=4)
        speed_cb.pack(side='left', padx=5)
        self.add_context_menu(speed_cb) # เพิ่มเมนูคลิกขวา
        speed_cb.set("1.0")
        
        pass 

    # *** ฟังก์ชันสำหรับ Live Control ***
    def toggle_tts_pause(self):
        if self.is_tts_paused.get():
            self.is_tts_paused.set(False)
            self.log_message("▶️ TTS กลับมาทำงานต่อ (Queue Resume)")
            new_text = "⏸️ Pause TTS"
        else:
            self.is_tts_paused.set(True)
            self.log_message("⏸️ TTS ถูกพักการทำงาน (Queue Paused)")
            new_text = "▶️ Resume TTS"
            
        # *** เพิ่ม Logic อัปเดตปุ่มทั้งสามแท็บ ***
        if self.pause_button:
            self.pause_button.config(text=new_text)
        if self.pause_button_twitch:
            self.pause_button_twitch.config(text=new_text)
        if self.pause_button_youtube:
            self.pause_button_youtube.config(text=new_text)
        # *****************************************

    def _run_skip_operation(self):
        """
        ฟังก์ชันนี้ทำงานในเธรดแยกเพื่อไม่ให้บล็อก GUI เมื่อมีการจัดการคิว/หยุดเสียง
        ใช้ Event เพื่อยืนยันการหยุดของ TTS Worker
        """
        # 1. สั่งหยุดเสียงที่กำลังเล่นอยู่ (ใน TTS Worker)
        if self.is_speaking.is_set():
            self.tts_queue.put('__STOP_SPEECH__')
            
            # รอ 1 วินาที เพื่อให้ TTS Worker หยุดพูด
            is_stopped = self.speech_stopped_event.wait(timeout=1)
            if not is_stopped:
                self.master.after(0, lambda: self.log_message("⚠️ Skip Warning: TTS Worker ไม่ตอบสนองการหยุดทันที"))

        last_comment = self.last_comment_for_skip
        
        # 2. *** แก้ไข: เคลียร์คิวที่เหลือทั้งหมดแบบ Non-Blocking ***
        try:
            while True:
                self.tts_queue.get_nowait()
                self.tts_queue.task_done()
        except queue.Empty:
            pass
            
        # 3. นำข้อความสุดท้ายกลับเข้าคิว
        if last_comment:
            self.tts_queue.put(last_comment) 
            self.last_comment_for_skip = None
            self.master.after(0, lambda: self.log_message("⏩ ข้ามคิว: อ่านข้อความล่าสุด"))
        else:
            self.last_comment_for_skip = None
            self.master.after(0, lambda: self.log_message("⏩ เคลียร์คิวทั้งหมดสำเร็จ"))

    def skip_comment(self):
        # *** แก้ไข: ย้าย Logic การ Skip ที่มี Lock/Blocking ไปทำงานในเธรดแยก ***
        if self.is_speaking.is_set() or self.tts_queue.qsize() > 0:
            self.log_message("⏳ ส่งคำสั่ง Skip Comment ไปยัง TTS Worker...")
            threading.Thread(target=self._run_skip_operation, daemon=True).start()
        else:
            self.log_message("❌ ไม่มีคอมเมนต์ในคิวที่จะข้ามได้")
        # *************************************************************************

    def open_live_in_browser(self):
        username = self.username_entry.get().strip()
        if not username:
            messagebox.showerror("Error", "กรอกชื่อ TikTok Username")
            return
            
        live_url = f"https://www.tiktok.com/@{username}/live"
        try:
            webbrowser.open_new_tab(live_url)
            self.log_message(f"🌐 เปิด Live ของ @{username} ในเบราว์เซอร์ (เบื้องหลัง)")
        except Exception as e:
            self.log_message(f"❌ ไม่สามารถเปิดเบราว์เซอร์ได้: {e}")

    def create_live_widgets(self, container):
        # 1. Username & Connect
        f1 = ttk.Frame(container); f1.pack(fill='x', pady=5)
        ttk.Label(f1, text="TikTok Username:").pack(side='left', padx=5)
        self.username_entry = ttk.Entry(f1, width=25) 
        self.username_entry.pack(side='left', padx=5, expand=True, fill='x')
        self.add_context_menu(self.username_entry) # เพิ่มเมนูคลิกขวา
        self.username_entry.insert(0, "sontayatongsima")
        
        # Connect Button
        self.connect_button = ttk.Button(f1, text="Connect", command=self.toggle_connection)
        self.connect_button.pack(side='left', padx=5)

        # 2. สถานะ (Status) - ใช้ Grid เพื่อลดพื้นที่แนวตั้งและจัดให้สมดุล
        status = ttk.LabelFrame(container, text="📊 สถานะ TikTok Live", padding=10); status.pack(fill='x', pady=10)
        
        # Row 0: Connection & Queue
        ttk.Label(status, text="สถานะการเชื่อมต่อ:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        self.connection_status_label = ttk.Label(status, textvariable=self.status_connection, font=('',10,'bold')); 
        self.connection_status_label.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        
        ttk.Label(status, text="คิวข้อความรวม:").grid(row=0, column=2, sticky='e', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_queue_count, font=('',9,'bold')).grid(row=0, column=3, sticky='w', padx=5, pady=2)
        
        # Row 1: Speaker
        ttk.Label(status, text="กำลังอ่าน:").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_speaker, foreground="blue", font=('',9,'bold')).grid(row=1, column=1, columnspan=3, sticky='w', padx=5, pady=2)

        # เพิ่มการขยายของคอลัมน์ 1 และ 3 เพื่อกระจายพื้นที่
        status.columnconfigure(1, weight=1)
        status.columnconfigure(3, weight=1)
        
        # *** 3. Real-time Statistics Area ***
        statsf = ttk.LabelFrame(container, text="📈 สถิติ Live", padding=10); statsf.pack(fill='x', expand=False, pady=(0, 10))
        
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
        
        # *** 4. Live Control (ปุ่มควบคุม) ***
        ctrl_frame = ttk.LabelFrame(container, text="🛠️ Live Control (TikTok)", padding=10)
        ctrl_frame.pack(fill='x', pady=10)

        # ใช้ Grid จัดเรียงปุ่ม
        ctrl_frame.columnconfigure(0, weight=1)
        ctrl_frame.columnconfigure(1, weight=1)

        # Row 0: Pause และ Skip
        initial_text = "▶️ Resume TTS" if self.is_tts_paused.get() else "⏸️ Pause TTS"
        self.pause_button = ttk.Button(ctrl_frame, text=initial_text, command=self.toggle_tts_pause)
        self.pause_button.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        ttk.Button(ctrl_frame, text="⏩ Skip Comment", command=self.skip_comment).grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        
        # Row 1: Open Live
        ttk.Button(ctrl_frame, text="🌐 Open Live Video", command=self.open_live_in_browser).grid(row=1, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        
        # Row 2: สรุปเสียงปัจจุบัน
        ttk.Label(ctrl_frame, text="Current Voice:").grid(row=2, column=0, sticky='w', padx=5, pady=2)
        
        # *** ใช้ตัวแปร Voice Summary ของ TikTok ***
        ttk.Label(ctrl_frame, textvariable=self.voice_summary_tiktok, foreground='blue', font=('', 9, 'bold')).grid(row=2, column=1, sticky='w', padx=5, pady=2)
        # *****************************************
        
        # *** ลบ ttk.Frame(container).pack(fill='both', expand=True) ออก เพื่อลดพื้นที่ว่าง ***
        # ttk.Frame(container).pack(fill='both', expand=True) 
        
    # *** ฟังก์ชันสำหรับ Twitch Control ***
    def toggle_twitch_connection(self):
        if not self.is_twitch_connected:
            if self.is_custom_tts_active.is_set():
                messagebox.showerror("Error", "สลับไปแท็บ Live Chat (Twitch) ก่อน")
                return
            if self.is_connected:
                messagebox.showerror("Error", "กรุณาตัดการเชื่อมต่อ TikTok ก่อน")
                return
            if self.is_youtube_connected:
                messagebox.showerror("Error", "กรุณาตัดการเชื่อมต่อ YouTube ก่อน")
                return
            
            # ดึงค่า Input ทั้งหมด
            channel = self.twitch_channel_entry.get().strip()
            bot_username = self.twitch_bot_username_entry.get().strip()
            oauth_token = self.twitch_oauth_token_entry.get().strip()
            
            app_id = self.twitch_id_entry.get().strip()
            app_secret = self.twitch_secret_entry.get().strip()
            
            # 1. ตรวจสอบ Channel, ID, Secret (ID/Secret ต้องกรอกเพื่อสร้าง Twitch Object)
            if not channel or not app_id or not app_secret:
                messagebox.showerror("Error", "กรุณากรอกข้อมูลให้ครบถ้วน (Channel, Client ID, Client Secret)")
                return

            # 2. ตรวจสอบ Token และ Username
            if not oauth_token or not bot_username:
                messagebox.showerror("Error", "กรุณากรอก Twitch OAuth Token และ Bot Username ที่ถูกต้อง")
                return

            # 3. *** โค้ดที่แก้ไข: จัดการเพิ่ม oauth: ให้โดยอัตโนมัติ ***
            if not oauth_token.startswith('oauth:'):
                self.log_message("🛠️ เพิ่ม 'oauth:' นำหน้า Token โดยอัตโนมัติ")
                oauth_token = f"oauth:{oauth_token}"
            
            # 4. Disable GUI
            self.twitch_channel_entry.config(state='disabled')
            self.twitch_bot_username_entry.config(state='disabled')
            self.twitch_oauth_token_entry.config(state='disabled')
            self.twitch_id_entry.config(state='disabled')
            self.twitch_secret_entry.config(state='disabled')
            self.twitch_connect_button.config(text="Connecting...", state='disabled')
            
            # เคลียร์สถานะ Live อื่นๆ
            self.is_connected = False
            self.is_youtube_connected = False
            
            self.twitch_chat_thread = threading.Thread(
                target=self.start_twitch_client, 
                args=(channel, bot_username, oauth_token, app_id, app_secret), 
                daemon=True
            )
            self.twitch_chat_thread.start()
        else:
            self.stop_twitch_client()
            
    def update_twitch_gui_after_disconnect(self):
        self.is_twitch_connected = False
        if self.twitch_channel_entry: self.twitch_channel_entry.config(state='normal')
        if self.twitch_bot_username_entry: self.twitch_bot_username_entry.config(state='normal')
        if self.twitch_oauth_token_entry: self.twitch_oauth_token_entry.config(state='normal')
        if self.twitch_id_entry: self.twitch_id_entry.config(state='normal')
        if self.twitch_secret_entry: self.twitch_secret_entry.config(state='normal')
        if self.twitch_connect_button: self.twitch_connect_button.config(text="Connect", state='normal')
        self.status_twitch_connection.set("Disconnected")

    def create_twitch_widgets(self, container):
        # 1. Credentials Input (สำคัญมาก)
        creds_frame = ttk.LabelFrame(container, text="🔑 Twitch Chat Credentials (ต้องใช้ค่าจริง)", padding=10)
        creds_frame.pack(fill='x', pady=5)
        
        # Grid Layout สำหรับ Credentials
        creds_frame.columnconfigure(1, weight=1)
        
        # *** 1. Client ID/Secret (สำหรับสร้าง Twitch Object) ***
        ttk.Label(creds_frame, text="Client ID:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        self.twitch_id_entry = ttk.Entry(creds_frame, width=30) 
        self.twitch_id_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        self.add_context_menu(self.twitch_id_entry) # เพิ่มเมนูคลิกขวา
        self.twitch_id_entry.insert(0, "YOUR_CLIENT_ID") 

        ttk.Label(creds_frame, text="Client Secret:").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        self.twitch_secret_entry = ttk.Entry(creds_frame, width=30, show='*') # ซ่อน
        self.twitch_secret_entry.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
        self.add_context_menu(self.twitch_secret_entry) # เพิ่มเมนูคลิกขวา
        self.twitch_secret_entry.insert(0, "YOUR_CLIENT_SECRET")

        # *** 2. OAuth Token และ Bot Username (สำหรับ Chat จริง) ***
        ttk.Label(creds_frame, text="OAuth Token:").grid(row=2, column=0, sticky='w', padx=5, pady=2)
        self.twitch_oauth_token_entry = ttk.Entry(creds_frame, width=30, show='*') # ซ่อน
        self.twitch_oauth_token_entry.grid(row=2, column=1, sticky='ew', padx=5, pady=2)
        self.add_context_menu(self.twitch_oauth_token_entry) # เพิ่มเมนูคลิกขวา
        self.twitch_oauth_token_entry.insert(0, "YOUR_TOKEN_KEY_HERE")
        
        ttk.Label(creds_frame, text="Bot Username:").grid(row=3, column=0, sticky='w', padx=5, pady=2)
        self.twitch_bot_username_entry = ttk.Entry(creds_frame, width=30)
        self.twitch_bot_username_entry.grid(row=3, column=1, sticky='ew', padx=5, pady=2)
        self.add_context_menu(self.twitch_bot_username_entry) # เพิ่มเมนูคลิกขวา
        self.twitch_bot_username_entry.insert(0, "your_bot_name")

        # *** 3. เพิ่มลิงก์อำนวยความสะดวก (ลิงก์ Token ถูกตัดให้สั้นลง) ***
        def open_twitch_dev_console(event):
            self.log_message("🌐 เปิด Twitch Developer Console...")
            webbrowser.open_new_tab("https://dev.twitch.tv/console/apps")
        
        def open_twitch_token_generator(event):
            self.log_message("🌐 เปิด Twitch Token Generator...")
            # *** ลิงก์ที่ถูกตัดแล้ว ***
            webbrowser.open_new_tab("https://twitchtokengenerator.com/") 

        link_frame = ttk.Frame(creds_frame)
        link_frame.grid(row=4, column=0, columnspan=2, sticky='w', padx=5, pady=5)
        
        link_dev = tk.Label(link_frame, text="Twitch Developers (ID/Secret)", 
                              fg="blue", cursor="hand2", underline=True)
        link_dev.pack(side='left', padx=(0, 10))
        link_dev.bind("<Button-1>", open_twitch_dev_console)

        link_token = tk.Label(link_frame, text="Token Generator (OAuth Token)", 
                              fg="blue", cursor="hand2", underline=True)
        link_token.pack(side='left')
        link_token.bind("<Button-1>", open_twitch_token_generator)
        # ******************************************************
        
        # 2. Channel Name & Connect
        f = ttk.Frame(container); f.pack(fill='x', pady=5)
        ttk.Label(f, text="Twitch Channel Name:").pack(side='left', padx=5)
        self.twitch_channel_entry = ttk.Entry(f, width=25) 
        self.twitch_channel_entry.pack(side='left', padx=5, expand=True, fill='x')
        self.add_context_menu(self.twitch_channel_entry) # เพิ่มเมนูคลิกขวา
        self.twitch_channel_entry.insert(0, "sontayatongsima") # ตัวอย่าง
        self.twitch_connect_button = ttk.Button(f, text="Connect", command=self.toggle_twitch_connection)
        self.twitch_connect_button.pack(side='left', padx=5)


        # 3. สถานะ Twitch (เหลือแค่ Connection Status และ Live Control)
        status = ttk.LabelFrame(container, text="📊 สถานะ Twitch Chat", padding=10); status.pack(fill='x', pady=10)
        
        # Row 0: Connection & Queue
        ttk.Label(status, text="สถานะการเชื่อมต่อ:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        self.twitch_status_label_indicator = ttk.Label(status, textvariable=self.status_twitch_connection, font=('',10,'bold'), foreground='red');
        self.twitch_status_label_indicator.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        
        ttk.Label(status, text="คิวข้อความรวม:").grid(row=0, column=2, sticky='e', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_queue_count, font=('',9,'bold')).grid(row=0, column=3, sticky='w', padx=5, pady=2)
        
        # Row 1: Speaker
        ttk.Label(status, text="กำลังอ่าน:").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_speaker, foreground="blue", font=('',9,'bold')).grid(row=1, column=1, columnspan=3, sticky='w', padx=5, pady=2)

        status.columnconfigure(1, weight=1)
        status.columnconfigure(3, weight=1)
        
        # *** 4. ปุ่มควบคุม Twitch ***
        ctrl_frame = ttk.LabelFrame(container, text="🛠️ Live Control (Twitch)", padding=10)
        # *** pack(fill='x', expand=True, pady=10) เพื่อให้ใช้พื้นที่ที่สถิติเคยอยู่ และดัน Log ขึ้น ***
        ctrl_frame.pack(fill='x', expand=True, pady=10) 
        
        # ใช้ Grid จัดเรียงปุ่ม
        ctrl_frame.columnconfigure(0, weight=1)
        ctrl_frame.columnconfigure(1, weight=1)
        
        # Row 0: Pause และ Skip
        initial_text = "▶️ Resume TTS" if self.is_tts_paused.get() else "⏸️ Pause TTS"
        self.pause_button_twitch = ttk.Button(ctrl_frame, text=initial_text, command=self.toggle_tts_pause)
        self.pause_button_twitch.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        
        ttk.Button(ctrl_frame, text="⏩ Skip Comment", command=self.skip_comment).grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        
        # Row 1: Open Live
        ttk.Button(ctrl_frame, text="🌐 Open Twitch Channel", command=self.open_twitch_channel).grid(row=1, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        
        # Row 2: สรุปเสียงปัจจุบัน
        ttk.Label(ctrl_frame, text="Current Voice:").grid(row=2, column=0, sticky='w', padx=5, pady=2)
        
        # *** ใช้ตัวแปร Voice Summary ของ Twitch ***
        ttk.Label(ctrl_frame, textvariable=self.voice_summary_twitch, foreground='blue', font=('', 9, 'bold')).grid(row=2, column=1, sticky='w', padx=5, pady=2)
        # *****************************************

        # *** ลบ ttk.Frame(container).pack(fill='both', expand=True) ออก เพื่อลดพื้นที่ว่าง ***
        # ttk.Frame(container).pack(fill='both', expand=True)
        
    # *** ฟังก์ชันสำหรับ YouTube Control ***
    def toggle_youtube_connection(self):
        if not self.is_youtube_connected:
            if self.is_custom_tts_active.is_set():
                messagebox.showerror("Error", "สลับไปแท็บ Live Chat (YouTube) ก่อน")
                return
            if self.is_connected:
                messagebox.showerror("Error", "กรุณาตัดการเชื่อมต่อ TikTok ก่อน")
                return
            if self.is_twitch_connected:
                messagebox.showerror("Error", "กรุณาตัดการเชื่อมต่อ Twitch ก่อน")
                return
            
            video_id = self.youtube_video_id_entry.get().strip()
            if not video_id or video_id == "ใส่ Video ID หรือ URL เต็มของ Live":
                messagebox.showerror("Error", "กรุณากรอก YouTube Video ID หรือ URL ที่ถูกต้อง")
                return

            self.youtube_video_id_entry.config(state='disabled')
            self.youtube_connect_button.config(text="Connecting...", state='disabled')
            
            # เคลียร์สถานะ Live อื่นๆ
            self.is_connected = False
            self.is_twitch_connected = False
            
            # Start the YouTube worker thread
            self.youtube_chat_thread = threading.Thread(target=self.start_youtube_client, args=(video_id,), daemon=True)
            self.youtube_chat_thread.start()
        else:
            self.stop_youtube_client()
            
    def update_youtube_gui_after_disconnect(self):
        self.is_youtube_connected = False
        if self.youtube_video_id_entry: self.youtube_video_id_entry.config(state='normal')
        if self.youtube_connect_button: self.youtube_connect_button.config(text="Connect", state='normal')
        self.status_youtube_connection.set("Disconnected")

    def create_youtube_widgets(self, container):
        # 1. Video ID / URL & Connect
        f = ttk.Frame(container); f.pack(fill='x', pady=5)
        ttk.Label(f, text="YouTube Video ID/URL:").pack(side='left', padx=5)
        self.youtube_video_id_entry = ttk.Entry(f, width=25) 
        self.youtube_video_id_entry.pack(side='left', padx=5, expand=True, fill='x')
        self.add_context_menu(self.youtube_video_id_entry) # เพิ่มเมนูคลิกขวา
        # ตัวอย่าง Video ID ของ Live สด
        self.youtube_video_id_entry.insert(0, "ใส่ Video ID หรือ URL เต็มของ Live") 
        self.youtube_connect_button = ttk.Button(f, text="Connect", command=self.toggle_youtube_connection)
        self.youtube_connect_button.pack(side='left', padx=5)


        # 2. สถานะ YouTube
        status = ttk.LabelFrame(container, text="📊 สถานะ YouTube Chat", padding=10); status.pack(fill='x', pady=10)
        
        # Row 0: Connection & Queue
        ttk.Label(status, text="สถานะการเชื่อมต่อ:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
        self.youtube_status_label_indicator = ttk.Label(status, textvariable=self.status_youtube_connection, font=('',10,'bold'), foreground='red');
        self.youtube_status_label_indicator.grid(row=0, column=1, sticky='w', padx=5, pady=2)
        
        ttk.Label(status, text="คิวข้อความรวม:").grid(row=0, column=2, sticky='e', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_queue_count, font=('',9,'bold')).grid(row=0, column=3, sticky='w', padx=5, pady=2)
        
        # Row 1: Speaker
        ttk.Label(status, text="กำลังอ่าน:").grid(row=1, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(status, textvariable=self.status_speaker, foreground="blue", font=('',9,'bold')).grid(row=1, column=1, columnspan=3, sticky='w', padx=5, pady=2)

        # เพิ่มการขยายของคอลัมน์ 1 และ 3 เพื่อกระจายพื้นที่
        status.columnconfigure(1, weight=1)
        status.columnconfigure(3, weight=1)
        
        # *** 3. Real-time Statistics Area (ย้ายขึ้นมา) ***
        statsf = ttk.LabelFrame(container, text="📈 สถิติ Live", padding=10); statsf.pack(fill='x', expand=False, pady=(0, 10))
        
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
        
        # 4. ปุ่มควบคุม YouTube
        ctrl_frame = ttk.LabelFrame(container, text="🛠️ Live Control (YouTube)", padding=10)
        ctrl_frame.pack(fill='x', pady=10)
        
        # ใช้ Grid จัดเรียงปุ่ม
        ctrl_frame.columnconfigure(0, weight=1)
        ctrl_frame.columnconfigure(1, weight=1)
        
        # Row 0: Skip Comment และ Open Live Video
        ttk.Button(ctrl_frame, text="⏩ Skip Comment", command=self.skip_comment).grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        ttk.Button(ctrl_frame, text="🌐 Open YouTube Video", command=self.open_youtube_video).grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        
        # Row 1: Pause TTS
        initial_text = "▶️ Resume TTS" if self.is_tts_paused.get() else "⏸️ Pause TTS"
        self.pause_button_youtube = ttk.Button(ctrl_frame, text=initial_text, command=self.toggle_tts_pause)
        self.pause_button_youtube.grid(row=1, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        
        # Row 2: สรุปเสียงปัจจุบัน
        ttk.Label(ctrl_frame, text="Current Voice:").grid(row=2, column=0, sticky='w', padx=5, pady=2)
        
        # *** ใช้ตัวแปร Voice Summary ของ YouTube ***
        ttk.Label(ctrl_frame, textvariable=self.voice_summary_youtube, foreground='blue', font=('', 9, 'bold')).grid(row=2, column=1, sticky='w', padx=5, pady=2)
        # *****************************************
        
        # *** ลบ ttk.Frame(container).pack(fill='both', expand=True) ออก เพื่อลดพื้นที่ว่าง ***
        # ttk.Frame(container).pack(fill='both', expand=True)


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
        self.add_context_menu(self.tts_text_entry) # เพิ่มเมนูคลิกขวา

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
        # *** ลบส่วน Global Real-time Statistics Area ที่เคยซ้ำซ้อนออก ***
        
        # 6. Log Area - อยู่ล่างสุดและมีขนาดคงที่
        logf = ttk.LabelFrame(container, text="📜 Log", padding=10); logf.pack(fill='both', expand=True, padx=10, pady=(0, 10)) 
        # *** แก้ไข: เพิ่ม height เป็น 15 เพื่อใช้พื้นที่ที่เพิ่มมาจากการลบสถิติ Twitch ***
        self.log_text = tk.Text(logf, height=15, state='disabled'); self.log_text.pack(fill='both', expand=True) 
        sb = ttk.Scrollbar(logf, command=self.log_text.yview); sb.pack(side='right', fill='y')
        self.log_text['yscrollcommand'] = sb.set
        self.add_context_menu(self.log_text) # เพิ่มเมนูคลิกขวา

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
        if (self.is_connected or self.is_twitch_connected or self.is_youtube_connected) and self.tts_queue.qsize() > 0:
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
    # Live Connection (TikTok)
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
                messagebox.showerror("Error", "สลับไปแท็บ Live Connection (TikTok) ก่อน")
                return
            if self.is_twitch_connected:
                messagebox.showerror("Error", "กรุณาตัดการเชื่อมต่อ Twitch ก่อน")
                return
            if self.is_youtube_connected:
                messagebox.showerror("Error", "กรุณาตัดการเชื่อมต่อ YouTube ก่อน")
                return

            user = self.username_entry.get().strip()
            # Session ID ถูกลบออกแล้ว
            
            if not user:
                messagebox.showerror("Error", "กรอกชื่อ TikTok Username")
                return
            
            self.username_entry.config(state='disabled')
            self.connect_button.config(text="Connecting...", state='disabled')
            
            # เคลียร์สถานะ Live อื่นๆ
            self.is_twitch_connected = False
            self.is_youtube_connected = False

            # เรียก start_client โดยไม่มี session_id
            threading.Thread(target=self.start_client, args=(user,), daemon=True).start()
        else:
            self.stop_client()

    def start_client(self, username):
        try:
            # ใช้ TikTokLiveClient(username) โดยตรง
            self.client = TikTokLiveClient(username)
            
            # *** แก้ไข: อัปเดต User-Agent เป็นเวอร์ชันล่าสุดเพื่อเลี่ยง "DEVICE_BLOCKED" ***
            self.client.headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": f"https://www.tiktok.com/@{username}/live",
    "Origin": "https://www.tiktok.com",
    "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}
            self.client.on(events.CommentEvent)(self.on_comment) 
            self.client.on(events.ConnectEvent)(self.on_connect_success) 
            self.client.on(events.DisconnectEvent)(self.on_disconnect) 
            self.client.run()
        except Exception as e:
            self.log_message(f"❌ TikTok เชื่อมต่อล้มเหลว: {e}")
            self.master.after(0, self.update_gui_after_disconnect)

    def stop_client(self):
        if self.client:
            self.log_message("⏳ กำลังตัดการเชื่อมต่อ TikTok...")
            with self.tts_queue.mutex: self.tts_queue.queue.clear()
            threading.Thread(target=self.client.disconnect, daemon=True).start()
            self.is_connected = False
            self.master.after(0, self.update_gui_after_disconnect)

    def update_gui_after_disconnect(self):
        self.is_connected = False
        self.client = None
        self.username_entry.config(state='normal')
        self.connect_button.config(text="Connect", state='normal')
        self.log_message("🔌 ตัดการเชื่อมต่อ TikTok แล้ว")
        self.status_speaker.set("-")
        self.comments_read_count.set(0)
        self.comments_filtered_count.set(0)
        self.avg_read_rate.set("-")
        self.is_tts_paused.set(False)

    async def on_comment(self, event: events.CommentEvent): 
        if not self.is_connected or self.is_custom_tts_active.is_set() or self.is_twitch_connected or self.is_youtube_connected: 
            return
            
        user = event.user.nickname
        comment = event.comment.strip()
        
        if not comment: return
        
        if len(comment) < 1 or len(comment) > 200: 
            # *** แก้ไข: ลบ [TikTok] ออกจาก Log ***
            self.log_message(f"🗑️ {user}: คอมเมนต์ถูกกรอง (ความยาว: {len(comment)})")
            self.master.after(0, lambda: self.comments_filtered_count.set(self.comments_filtered_count.get() + 1))
            return
        
        # *** แก้ไข: ลบ [TikTok] ออกจาก Log ***
        self.log_message(f"💬 {user}: {comment}")
        # *** แก้ไข: ลบคำนำหน้าแพลตฟอร์มออก (TTS จะพูดแค่: "ชื่อผู้ใช้ พูดว่า ข้อความ") ***
        tts_text = f"{user} พูดว่า {comment}"
        self.last_comment_for_skip = tts_text 
        
        self.speak_async(tts_text)

    async def on_connect_success(self, event: events.ConnectEvent): 
        self.master.after(0, lambda: self.connect_button.config(text="Disconnect", state='normal'))
        self.is_connected = True
        self.live_start_time = time.time()
        self.log_message(f"✅ เชื่อมต่อ TikTok @{self.client.unique_id} สำเร็จ!")
        self.speak_async("เชื่อมต่อ TikTok สำเร็จ")

    async def on_disconnect(self, event: events.DisconnectEvent): 
        self.log_message("⚠️ TikTok หลุดการเชื่อมต่อ")
        self.master.after(0, self.update_gui_after_disconnect)

    # -----------------------------------------------------------------
    # Twitch Connection (แก้ไข: ใช้ irc.bot โดยตรง - ตัดปัญหา twitchAPI)
    # -----------------------------------------------------------------
    
    # *** คลาส Bot ภายในสำหรับจัดการ IRC Connection ***
    class SimpleTwitchBot(irc.bot.SingleServerIRCBot):
        def __init__(self, channel, nickname, token, app_instance):
            self.app = app_instance
            self.channel = '#' + channel
            self.token = token.replace('oauth:', 'oauth:') # ให้แน่ใจว่ามี oauth: นำหน้า
            self.nickname = nickname
            
            # Twitch IRC server
            server = 'irc.chat.twitch.tv'
            port = 6667
            
            irc.bot.SingleServerIRCBot.__init__(self, [(server, port, self.token)], nickname, nickname)
            
            self.app.log_message(f"⏳ Bot: {self.nickname} กำลังพยายามเชื่อมต่อ IRC...")

        def on_welcome(self, c, e):
            self.app.log_message(f"✅ IRC: เชื่อมต่อสำเร็จ! กำลังเข้าร่วมช่อง {self.channel}")
            c.join(self.channel)
            
            # Update GUI/State
            self.app.is_twitch_connected = True
            self.app.live_start_time = time.time()
            self.app.master.after(0, lambda: self.app.twitch_connect_button.config(text="Disconnect", state='normal'))
            self.app.master.after(0, lambda: self.app.status_twitch_connection.set("Connected"))
            self.app.speak_async(f"เชื่อมต่อ Twitch ช่อง {self.channel.lstrip('#')} สำเร็จ")

        def on_pubmsg(self, c, e):
            # ดึงข้อความแชท
            user = e.source.nick
            comment = e.arguments[0].strip()
            
            # ส่งต่อข้อความไปยัง TTS Queue ของแอปหลัก
            self.app.master.after(0, lambda: self.app.handle_twitch_message(user, comment))

        def on_disconnect(self, c, e):
            self.app.log_message(f"⚠️ IRC: หลุดการเชื่อมต่อ {e.arguments[0]}")
            self.app.master.after(0, self.app.update_twitch_gui_after_disconnect)
        
        def on_error(self, c, e):
            self.app.log_message(f"❌ IRC Error: {e.arguments[0]}")
            self.app.master.after(0, self.app.update_twitch_gui_after_disconnect)


    def handle_twitch_message(self, user, comment):
        """จัดการข้อความที่ได้รับจาก SimpleTwitchBot"""
        if not self.is_twitch_connected or self.is_custom_tts_active.is_set() or self.is_connected or self.is_youtube_connected:
            return
            
        if not comment: return
        
        if len(comment) < 1 or len(comment) > 200: 
            # *** แก้ไข: ลบ [Twitch] ออกจาก Log ***
            self.log_message(f"🗑️ {user}: คอมเมนต์ถูกกรอง (ความยาว: {len(comment)})")
            self.master.after(0, lambda: self.comments_filtered_count.set(self.comments_filtered_count.get() + 1))
            return
        
        # *** แก้ไข: ลบ [Twitch] ออกจาก Log ***
        self.log_message(f"💬 {user}: {comment}")
        # *** แก้ไข: ลบคำนำหน้าแพลตฟอร์มออก (TTS จะพูดแค่: "ชื่อผู้ใช้ พูดว่า ข้อความ") ***
        tts_text = f"{user} พูดว่า {comment}"
        self.last_comment_for_skip = tts_text 
        
        self.speak_async(tts_text)


    def start_twitch_client(self, channel_name, bot_username, oauth_token, app_id, app_secret):
        # Note: app_id/app_secret ถูกส่งมาแต่จะถูกละเลย เพราะใช้ IRC โดยตรง
        try:
            # ใช้ TwitchBot Client
            self.twitch_client = self.SimpleTwitchBot(
                channel=channel_name,
                nickname=bot_username,
                token=oauth_token,
                app_instance=self
            )
            
            # Start IRC Bot (จะบล็อก Thread นี้)
            self.twitch_client.start()
            
            # หาก Bot ถูกหยุด จะมาถึงบรรทัดนี้
            self.master.after(0, self.update_twitch_gui_after_disconnect)

        except Exception as e:
            self.log_message(f"❌ Twitch เชื่อมต่อล้มเหลว (IRC): {e}")
            self.master.after(0, self.update_twitch_gui_after_disconnect)


    def stop_twitch_client(self):
        if self.twitch_client:
            self.log_message("⏳ กำลังตัดการเชื่อมต่อ Twitch...")
            
            # การหยุด IRC Bot
            threading.Thread(target=self.twitch_client.disconnect, daemon=True).start()
            
            self.is_twitch_connected = False
            self.master.after(0, self.update_twitch_gui_after_disconnect)
            
    # on_twitch_ready และ on_twitch_message ถูกย้ายไปอยู่ในคลาส SimpleTwitchBot แล้ว
        
    # -----------------------------------------------------------------
    # YouTube Connection (Synchronous Polling in Worker Thread)
    # -----------------------------------------------------------------
    def start_youtube_client(self, video_id):
        # แยก Video ID ออกจาก URL เต็ม (ในกรณีที่ผู้ใช้ใส่ URL เต็มมา)
        if "v=" in video_id:
            try:
                parsed = urllib.parse.urlparse(video_id)
                video_id = urllib.parse.parse_qs(parsed.query).get('v', [video_id])[0]
            except:
                pass
        
        try:
            # *** แก้ไข: เพิ่ม interruptable=False เพื่อปิดการใช้ signal ***
            self.youtube_chat = pytchat.create(
                video_id=video_id, 
                force_replay=False,
                interruptable=False  # <-- สำคัญ: แก้ไข signal error
            )
            
            self.log_message(f"✅ เชื่อมต่อ YouTube ID: {video_id} สำเร็จ! กำลังดึงแชท...")
            self.is_youtube_connected = True
            self.live_start_time = time.time()
            self.master.after(0, lambda: self.youtube_connect_button.config(text="Disconnect", state='normal'))
            self.master.after(0, lambda: self.status_youtube_connection.set("Connected"))
            
            # *** แก้ไข: เรียก speak_async ผ่าน master.after(0, ...) เพื่อหลีกเลี่ยง thread issue ***
            self.master.after(0, lambda: self.speak_async("เชื่อมต่อ YouTube สำเร็จ"))
            
            # Start the main chat loop (เรียก Worker โดยตรงในเธรดนี้)
            self._youtube_chat_worker()

        except pytchat.exceptions.InvalidVideoIdException:
            self.log_message(f"❌ YouTube เชื่อมต่อล้มเหลว: Invalid Video ID ({video_id})")
            self.master.after(0, self.update_youtube_gui_after_disconnect)
        except Exception as e:
            self.log_message(f"❌ YouTube เชื่อมต่อ/ดึงแชทล้มเหลว: {e}")
            self.master.after(0, self.update_youtube_gui_after_disconnect)
        finally:
            self.is_youtube_connected = False
            self.master.after(0, self.update_youtube_gui_after_disconnect)
            
    # *** เปลี่ยนจาก async def เป็น def ธรรมดา ***
    def _youtube_chat_worker(self):
        # Loop ดึงข้อความแชท
        while self.is_youtube_connected:
            try:
                if not self.youtube_chat.is_alive():
                    break
                    
                # ใช้ get().sync_items() สำหรับการดึงข้อมูลแบบ Synchronous
                for c in self.youtube_chat.get().sync_items():
                    # ตรวจสอบอีกครั้งเพื่อความปลอดภัย
                    if not self.is_youtube_connected: 
                        break 
                    
                    # Process YouTube chat message
                    user = c.author.name
                    comment = c.message.strip()

                    if not comment: 
                        continue

                    if len(comment) < 1 or len(comment) > 200: 
                        # *** แก้ไข: ลบ [YouTube] ออกจาก Log ***
                        self.log_message(f"🗑️ {user}: คอมเมนต์ถูกกรอง (ความยาว: {len(comment)})")
                        self.master.after(0, lambda: self.comments_filtered_count.set(self.comments_filtered_count.get() + 1))
                        continue
                    
                    # *** แก้ไข: ลบ [YouTube] ออกจาก Log ***
                    self.log_message(f"💬 {user}: {comment}")
                    # *** แก้ไข: ลบคำนำหน้าแพลตฟอร์มออก (TTS จะพูดแค่: "ชื่อผู้ใช้ พูดว่า ข้อความ") ***
                    tts_text = f"{user} พูดว่า {comment}"
                    self.last_comment_for_skip = tts_text 
                    
                    # *** แก้ไข: เรียก speak_async ผ่าน master.after(0, ...) เพื่อหลีกเลี่ยง thread issue ***
                    self.master.after(0, lambda t=tts_text: self.speak_async(t))
                    
            except KeyboardInterrupt:
                # Ignore keyboard interrupt in thread
                pass
            except Exception as e:
                # e.g. Connection lost, chat ended unexpectedly
                if 'Chat ended' in str(e) or 'Video offline' in str(e):
                    self.log_message("⚠️ YouTube Live Chat สิ้นสุดลง")
                    self.is_youtube_connected = False
                    break
                else:
                    self.log_message(f"⚠️ YouTube Chat Worker Error: {e}")
                # ใส่ sleep เพื่อไม่ให้ CPU โหลดสูงจากการ Polling ซ้ำๆ
                time.sleep(1) 
                
        self.log_message("🔌 YouTube Chat Worker หยุดทำงาน")


    def stop_youtube_client(self):
        if self.youtube_chat:
            self.log_message("⏳ กำลังตัดการเชื่อมต่อ YouTube...")
            
            # การหยุด pytchat
            if self.youtube_chat.is_alive():
                # ใช้ terminate() สำหรับอ็อบเจกต์ pytchat Synchronous (Blocking)
                self.youtube_chat.terminate() 
            
            self.is_youtube_connected = False
            self.master.after(0, self.update_youtube_gui_after_disconnect)


    # -----------------------------------------------------------------
    # TTS Worker
    # -----------------------------------------------------------------
    def tts_worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while True:
            # *** เพิ่ม: เคลียร์ Event เก่าก่อนรอข้อความใหม่ ***
            self.speech_stopped_event.clear()
            
            text = self.tts_queue.get()
            if text is None: break
            
            # *** แก้ไข: ตรวจสอบคำสั่งหยุดทันที (Stop Command) และ Set Event ***
            if text == '__STOP_SPEECH__':
                if self.is_speaking.is_set():
                    pygame.mixer.music.stop()
                    self.is_speaking.clear()
                    self.master.after(0, lambda: self.status_speaker.set("-"))
                    self.log_message("🛑 TTS Worker: หยุดพูดตามคำสั่ง")
                
                self.speech_stopped_event.set()
                self.tts_queue.task_done()
                continue
            # ****************************************************
            
            if self.is_tts_paused.get():
                self.tts_queue.put(text)
                time.sleep(0.5)
                continue
            
            # ปรับปรุงการตรวจสอบการเชื่อมต่อ: ตรวจสอบทั้ง TikTok, Twitch, และ YouTube
            if self.is_custom_tts_active.is_set() or (not self.is_connected and not self.is_twitch_connected and not self.is_youtube_connected):
                self.tts_queue.task_done()
                continue
            # ***********************************

            self.is_speaking.set()
            temp_file = os.path.join(tempfile.gettempdir(), f"live_{uuid.uuid4()}.mp3")
            try:
                # *** แก้ไข: เปลี่ยนการแสดง log ให้แสดงข้อความเต็มโดยไม่มีชื่อแพลตฟอร์มแล้ว ***
                self.log_message(f"🎧 กำลังสร้างเสียง: {text.split(' พูดว่า ')[1][:30]}...")
                loop.run_until_complete(self._generate_tts_async(text, temp_file))
                
                if not os.path.exists(temp_file) or os.path.getsize(temp_file) == 0:
                    raise Exception("ไฟล์เสียงว่างเปล่า")

                # *** แก้ไข: ปรับการแยก Speaker ใหม่: ให้ถือว่าข้อความทั้งหมดก่อน ' พูดว่า ' คือชื่อผู้ใช้ ***
                try:
                    speaker = text.split(" พูดว่า ")[0] 
                except IndexError:
                    speaker = "Unknown" # Fallback ถ้าข้อความไม่ได้อยู่ในรูปแบบที่คาดหวัง
                    
                self.master.after(0, lambda n=speaker: self.status_speaker.set(n))
                pygame.mixer.music.load(temp_file)
                pygame.mixer.music.play()
                
                while pygame.mixer.music.get_busy():
                    # การตรวจสอบเงื่อนไขการหลุดการเชื่อมต่อ
                    if not self.is_connected and not self.is_twitch_connected and not self.is_youtube_connected: 
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
