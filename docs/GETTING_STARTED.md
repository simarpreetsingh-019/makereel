# Getting started with makereel

makereel turns live streams and videos into short, captioned vertical reels, with the creator credited
on every one. It runs on your own computer: nothing is uploaded anywhere.

## 1. Install (one command)

You don't need Python or anything else first. The installer gets what's missing.

**Windows 10/11:** open **PowerShell** (Start menu → type "PowerShell") and paste:

```powershell
irm https://raw.githubusercontent.com/simarpreetsingh-019/makereel/main/install.ps1 | iex
```

**macOS or Linux:** open **Terminal** and paste:

```bash
curl -LsSf https://raw.githubusercontent.com/simarpreetsingh-019/makereel/main/install.sh | bash
```

It takes a few minutes. When it's done, makereel opens in your browser. Next time, open it with the
**makereel** shortcut (Windows: desktop or Start menu; macOS: `makereel.command` on the desktop).

## 2. First run: pick speech models (1 minute)

makereel listens to the video to write captions. Go to **System → Speech models for this computer**:

1. Choose who you clip: **English streamers**, **Indian streamers** (Hindi, Hinglish…), or both.
2. makereel suggests models that suit your computer. Press **Download and use these**.

Changed your mind mid-download? **Stop** it under "Downloaded models", or **Delete** a model you don't use.

## 3. Make your first reels

On **Create**, paste any link: a live stream, a past stream, a long video or a Short. Then press
**Make reels**.

- **A live stream** is recorded, and a reel is made each time something big happens (loud moments,
  busy chat). Each reel is as long as its moment, from about 30 seconds up to your longest-reel setting.
- **Anything else** is clipped straight away: its best moments become reels.

You can also upload a video file you already have.

Watch progress under **Jobs**. Clear finished ones with **×** or **Clear finished**.

## 4. Edit a reel

Open **Reels**, pick a video's folder, then **Edit** on a reel:

| Tab | What you can do |
|---|---|
| **Text** | Caption language (original script, English letters, or English translation), fix any word, the on-screen title |
| **Timing** | Shift captions earlier or later, or tap along to the audio |
| **Look** | Caption style, size, position, the layout (follow the speaker, split screen, blurred background…) |
| **Cards** | Quote and note cards, an outro |
| **Camera** | When following the speaker: move cuts, point a shot at someone, or show everyone |
| **Cut** | Trim, split in two, or **Make short versions** of a long reel |
| **Export** | The same reel as 9:16, 4:5, 1:1 or 16:9 |

Every save re-renders the reel in a few seconds.

## 5. Clip channels 24/7 (optional)

In **Settings**, add channels (one per line, e.g. `@CarryisLive`) and turn on **Watch my channels**.
makereel checks them every few minutes and clips them when they go live. It can also clip **new
uploads and premieres**, from now on or from the last 24/48 hours. Leave makereel open for this.

If jobs say **"Sign in to confirm you're not a bot"**, YouTube wants a signed-in viewer. makereel shows
a card: open YouTube in your browser, make sure you're signed in, pick that browser, and continue.

## 6. Make it yours

- **Brand:** your logo, caption font and colours, and the **creator badge** (the streamer's picture and
  @handle in a corner of every reel).
- **Settings → Where files are saved:** choose your reels folder, open it in Finder/Explorer, and
  **Clear cache** to free space.

## Updates

When a new version is out, a card tells you what's new, with **Update now**. System → Updates has the details.

## Need help?

Open an issue on GitHub with what you did and what happened. **System** shows your computer's details
to include.
