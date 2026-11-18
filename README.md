# Capri Anthem

Capri Anthem là bot nhạc Discord mã nguồn mở viết bằng Python và tự host trên Raspberry Pi 5. Vào kênh thoại, chọn bài từ YouTube, rồi điều khiển nhạc ngay trên tin nhắn của bot. Bạn có thể lưu những bài hay vào playlist, chia sẻ playlist bằng mã ID và mở khung hồ sơ bằng XP nghe nhạc.

Giao diện và lệnh trợ giúp trong Discord dùng tiếng Việt.

## Dùng bot trong Discord

1. Vào kênh thoại và dùng `/play query:…`. Dán link một video YouTube để thêm trực tiếp, hoặc nhập tên bài hay nghệ sĩ rồi chọn trong danh sách kết quả.
2. Dùng các nút dưới bài đang phát để tạm dừng, tiếp tục, bỏ qua, dừng, xem hàng đợi, lặp bài hoặc lưu vào playlist.
3. Dùng `/rank` để xem cấp, XP, thời gian nghe và số bài đã yêu cầu. Dùng `/help` nếu cần tra lệnh hoặc luật XP ngay trong Discord.

| Lệnh | Dùng khi |
| --- | --- |
| `/play query:…` | Tìm bài theo từ khóa hoặc thêm một video YouTube bằng link |
| `/random keyword:lofi count:5` | Thêm ngẫu nhiên từ 1 đến 10 bài theo từ khóa |
| `/queue` | Xem bài hiện tại và các bài đang chờ |
| `/pause`, `/resume`, `/skip`, `/stop` | Điều khiển phát nhạc. `/stop` cũng xóa hàng đợi |
| `/join`, `/leave` | Mời bot vào hoặc cho bot rời kênh thoại |
| `/rank [member]`, `/leaderboard`, `/frames` | Xem thẻ cá nhân, top 10 của server và các mốc mở khóa khung |

Hàng đợi chứa tối đa 100 bài đang chờ. Bot hỗ trợ link video YouTube đơn lẻ. Playlist được quản lý qua các lệnh bên dưới.

Bot tự rời kênh thoại sau 1 phút không có người hoặc sau 10 phút không phát nhạc và hàng đợi trống. Bot gửi lý do vào kênh chat nơi nhận lệnh gọi hoặc phát nhạc gần nhất.

## Playlist cá nhân và playlist công khai

- **Tạo và thêm bài.** Dùng `/playlist create name:…`, rồi bấm **Lưu vào playlist** dưới bài đang phát. Bạn cũng có thể mở `/playlist info`, chọn playlist của mình và bấm **Thêm bài hát** để dán link mà không cần phát trước.
- **Chỉnh danh sách.** Trong `/playlist info`, chủ playlist có thể đổi vị trí hoặc xóa bài. Dùng `/playlist delete name:…` để xóa cả playlist.
- **Chia sẻ.** Playlist mới mặc định riêng tư. Dùng `/playlist visibility` để chuyển sang công khai và `/playlist public` để tìm mã của playlist công khai.
- **Phát lại.** Dùng `/playlist play name name:…` cho playlist của bạn hoặc `/playlist play public public_id:…` cho playlist công khai. Tùy chọn `order` cho phép phát theo thứ tự đã lưu hoặc xáo trộn.

## XP và Capri Hack

| Hoạt động | XP |
| --- | --- |
| Đang nghe nhạc trong cùng kênh, bật nghe | 10 XP/phút nghe đủ điều kiện |
| Thêm bài thành công qua `/play` hoặc phát playlist | +2 XP/bài cho người yêu cầu |
| Người yêu cầu nghe bài thường từ đầu đến lúc kết thúc tự nhiên | +5 XP |
| Nghe bài từ `/random` | XP theo thời gian nghe |
| Có mặt trong kênh và bật nghe khi bài Capri Hack kết thúc tự nhiên | +200 XP, ngoài XP theo thời gian nghe |

Rời kênh, tắt nghe hoặc tạm dừng nhạc sẽ ngừng tích XP theo thời gian. XP và xếp hạng được lưu riêng cho từng server. Trong `/rank`, bạn có thể trang bị danh hiệu đã mở và dùng `/frames` để xem các khung tiếp theo.

**Capri Hack** là lượt phát bất ngờ sau khi một bài kết thúc tự nhiên. Khi đủ điều kiện, bot có 30% cơ hội tìm bài cùng nghệ sĩ và kiểu nhạc với bài thường gần nhất, với khoảng chờ 15 phút sau một lượt chọn thành công. Nếu tìm được bài phù hợp, nó phát trước hàng đợi còn lại. Bot bỏ qua lượt nếu thiếu thông tin hoặc không tìm được bài đủ khớp.

## Tự chạy trên Linux hoặc Raspberry Pi OS

### Chuẩn bị

- Python 3.13 và FFmpeg có trên `PATH`. Cài font DejaVu Sans để bot có font dự phòng khi render ảnh.
- Deno tương ứng với kiến trúc máy, đặt tại `bin/deno` trong repo và cấp quyền thực thi.
- Một ứng dụng bot trong Discord Developer Portal. Khi mời bot, chọn scope `bot` và `applications.commands`. Cấp quyền **View Channel**, **Send Messages**, **Connect** và **Speak**. Cấp thêm **Embed Links** và **Attach Files** để dùng đầy đủ bảng điều khiển và thẻ rank.

### Cài và chạy thử

```bash
git clone https://github.com/caonguyennhathoang/capri-anthem.git ~/capri-anthem
cd ~/capri-anthem
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
bash anthem configure
.venv/bin/python bot.py
```

`anthem configure` sẽ hỏi token Discord và lưu vào `~/.config/capri-anthem/token`. Khi bot online, vào kênh thoại và thử `/help` rồi `/play`.

### Chạy nền với systemd

Từ thư mục `~/capri-anthem`, dừng phiên chạy thử trước khi khởi động dịch vụ.

```bash
install -Dm644 capri-anthem.service ~/.config/systemd/user/capri-anthem.service
systemctl --user daemon-reload
bash anthem start
bash anthem status
```

Dùng `bash anthem logs` để xem log và `bash anthem stop` để dừng dịch vụ.

## Cấu trúc mã nguồn

| File | Vai trò |
| --- | --- |
| [bot.py](bot.py) | Kết nối Discord, đăng ký lệnh theo server và quản lý kết nối thoại |
| [music.py](music.py) | Hàng đợi theo server, tìm nhạc, phát audio, nút điều khiển và Capri Hack |
| [playlists.py](playlists.py) | Lưu playlist SQLite, quyền chỉnh sửa và chia sẻ qua ID |
| [levels.py](levels.py) | Theo dõi thời gian nghe, tính XP, chọn danh hiệu và xếp hạng |
| [rank_card.py](rank_card.py), [leaderboard_card.py](leaderboard_card.py), [rank_titles.py](rank_titles.py) | Render thẻ rank, bảng xếp hạng và khung bằng Pillow |
| [help_ui.py](help_ui.py) | Hướng dẫn và luật XP trong Discord |

yt-dlp tải âm thanh vào thư mục tạm theo từng bài. FFmpeg xử lý audio để bot phát qua Discord voice. Playlist chỉ lưu link và thông tin bài. Cơ sở dữ liệu SQLite và log nằm trong `~/.local/state/capri-anthem/` của máy chạy bot.

Chạy kiểm thử cục bộ bằng `.venv/bin/python -m unittest discover -v`.

## Giấy phép

Mã nguồn và tài liệu trong repo dùng [giấy phép MIT](LICENSE). Các thư viện và công cụ phụ thuộc có giấy phép riêng. Thẻ rank có hình trang trí dự phòng để chạy với bản mã nguồn công khai, nơi không kèm bộ ảnh nhân vật của bản cá nhân.
