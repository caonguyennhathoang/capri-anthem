# Capri Anthem

Bot nhạc Discord tự viết bằng Python, chạy trên Raspberry Pi 5. Dự án kết hợp phát nhạc trong kênh thoại, playlist cá nhân và hệ thống XP theo thời gian nghe.

- **Phát nhạc:** tìm bài YouTube, thêm bài ngẫu nhiên theo từ khóa, điều khiển hàng đợi và lặp bài bằng nút Discord.
- **Playlist:** lưu từ link hoặc bài đang phát, sắp xếp bài, phát theo thứ tự hoặc xáo trộn, chia sẻ playlist công khai bằng ID.
- **XP và danh hiệu:** lưu dữ liệu bằng SQLite, hiển thị thẻ `/rank`, bảng xếp hạng và khung trong `/frames`.
- **Capri Hack:** đề xuất một bài cùng nghệ sĩ và kiểu nhạc, có thưởng XP khi sự kiện hoàn tất.
- **Hướng dẫn:** dùng `/help` trong Discord để xem lệnh và luật XP.

## Chạy trên Linux hoặc Raspberry Pi OS

Cần Python 3.13, FFmpeg trên `PATH` và Deno tại `bin/deno`. Tạo ứng dụng bot trong Discord Developer Portal, mời bằng scope `bot` và `applications.commands`, rồi cấp quyền xem kênh, gửi tin nhắn, kết nối và nói. Các quyền nhúng liên kết và đính kèm tệp giúp hiển thị bảng điều khiển và ảnh rank.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
bash anthem configure
.venv/bin/python bot.py
```

Muốn chạy nền bằng systemd, đặt dự án tại `~/capri-anthem`, sao chép `capri-anthem.service` vào `~/.config/systemd/user/`, chạy `systemctl --user daemon-reload`, rồi dùng `bash anthem start`. Xem trạng thái và log bằng `bash anthem status` và `bash anthem logs`.

```bash
.venv/bin/python -m unittest discover -v
```

## Mã nguồn và tài nguyên

Logic hàng đợi, playlist, XP và giao diện bot được viết cho dự án này. Bot sử dụng discord.py, davey, yt-dlp, FFmpeg và Pillow. Các phần phụ thuộc có giấy phép riêng.

Mã nguồn và tài liệu trong repo dùng [giấy phép MIT](LICENSE).

Ảnh nhân vật của bản cá nhân nằm trong `rank_art/` và được loại khỏi repo. Thẻ rank có hình trang trí dự phòng khi không có ảnh nhân vật. Token được nhập trên máy chạy bot, còn cơ sở dữ liệu và log nằm trong thư mục trạng thái của máy đó.
