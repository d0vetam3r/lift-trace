# Step-by-step user guide

[English](USER_GUIDE.en.md) · [한국어](USER_GUIDE.ko.md) · [日本語](USER_GUIDE.ja.md) · [Home](../README.md)

Follow this order: **download → extract → open the app → enter game numbers → set up keys and scratch → paste into OBS**. You do not need to type commands or install Python.

Have a Windows 10/11 (64-bit) PC and controller ready. OBS Studio and INFINITAS are separate installations. Start the OBS steps below with **your game already visible in OBS**.

## 1. Download and open the app

1. On the project's GitHub page, click **Releases**, usually on the right.
2. Open the latest version and click **Assets** to see the files you can download.
3. Download the file whose name starts with `lift-trace-windows-x64-` and ends with `.zip`. The numbers in between are the version and may change. Do not choose “Source code” or a file with “source” in its name.
4. Right-click the downloaded file and choose **Extract All**. Choose a folder such as **Documents**, then click **Extract**.
5. Open the new folder, then the **LiftTrace** folder inside it. Double-click **LiftTrace.exe**. Windows may display its name as just **LiftTrace**.

**What you should see:** a small **Lift Trace window** and a **settings page** in your usual web browser. If the page does not appear, click **Open settings** in the small window. Select **English** if needed.

Keep the whole extracted folder together. **Do not move LiftTrace.exe on its own.** Double-click the same file next time.

In this guide, an **input note** is a picture of a key press or scratch movement. The app creates it from your controller input; it does not read notes from the game chart.

## 2. Enter the numbers from your game

Open the game's HI-SPEED settings and enter **your own values** in these boxes.

| Box to fill in | What to look for in the game |
| --- | --- |
| **Green number** | The green **NOTES TIME** number |
| **LIFT** | The amount of the lower LIFT cover |
| **SUDDEN+** | The amount of the upper SUDDEN+ cover; enter **0** if unused |

If there are two cover numbers, identify the upper SUDDEN+ value and the lower LIFT value. Do not enter the HI-SPEED multiplier or BPM in these boxes.

![Diagram of the upper cover, game notes, judgment line and lower display area](images/lane-layout.svg)

In the diagram, **A** is SUDDEN+, **B** is the game-note area, **C** is the judgment line and **D** is the lower LIFT area where your input notes go. This is an illustration; its numbers are examples.

Leave **Height setting** on **Match LIFT automatically (recommended)**. For example, LIFT **401** gives a display height of **290**. Use the value from your own game, not this example. Leave **Speed correction** at **1** to start.

**What you should see:** the app calculates a number in **Overlay height**. You will check the falling input notes after setting up the keys in the next step.

**When height is automatic and LIFT is 0, there is no space below the judgment line to show input notes.** Turn on LIFT in the game and enter its value. To choose a separate display height instead, select **Height setting → Set manually** and enter the height you want.

## 3. Follow the key and scratch setup prompts

1. Connect the controller to the PC in the mode you normally use for INFINITAS.
2. On the settings page, change **Input source** to **Controller · works while playing**.
3. Under **Controller**, select your device. If the list is empty, click **Scan**.
4. Click **Controller setup**. First, release every button.
5. Follow the prompts to press and release **keys 1 through 7**, from left to right, one at a time.
6. At the **clockwise ↻** prompt, look down at the turntable and turn it **only in the direction that clock hands move**. Do not press other buttons. After turning it, click **Check clockwise**.
7. At the next **counterclockwise ↺** prompt, turn it **only in the opposite direction to clock hands**, then click **Check counterclockwise**.
8. When the result appears, click **Apply**. To redo it, choose **Start again**; to leave without changing the setup, choose **Cancel**.
9. Choose **1P** if the scratch is on the left or **2P** if it is on the right.

**What you should see:** the setup closes. Press a key or turn the turntable: input notes fall in the lower part of the preview. The notes in the upper preview are examples, not a view of your running game.

If asked to set the directions again, click **Set rotation directions again**. This keeps keys 1–7 and repeats both scratch directions, starting with clockwise. If you unplugged the controller during setup, reconnect it and start again.

Check the scratch display too.

| Direction you turn | Input note on screen |
| --- | --- |
| Clockwise | **↻** and **light coral** |
| Counterclockwise | **↺** and **deep coral** |

Alternating directions changes both the arrow and color. If they are reversed, repeat **Controller setup** and check that you followed each direction prompt. Continuous movement in one direction may appear as one connected input note. The app does not read the chart, so it cannot divide that movement into the game's individual scratch notes.

## 4. Paste the address and size into OBS

First, in OBS, check **Settings → Video → Base (Canvas) Resolution** is **1920 × 1080**. The size and position below assume the game fills that whole picture.

For the steps below, switch between Lift Trace's settings page and OBS. Click the box you want to fill in, hold **Ctrl** and press **A** to select everything in that box. Then hold **Ctrl** and press **V** to replace it with what you copied. These shortcuts are written as **Ctrl+A** and **Ctrl+V** below.

1. For your first setup, find **Overlay area** in Lift Trace and click **Match 1080p lane size**. This sets the total width to **432** and adjusts the key and scratch widths together. It keeps your game numbers and controller setup.
2. Click **Copy address for OBS**.
3. In OBS, click the **+** below **Sources**, then choose **Browser**. Name it **Lift Input** and click **OK**.
4. In the new window, leave **Local file** unchecked. Click the **URL** box, then press **Ctrl+A** followed by **Ctrl+V**. This replaces its old contents with the copied address.
5. Return to Lift Trace and click **Copy width**. In OBS, click the **Width** box, then press **Ctrl+A** and **Ctrl+V**.
6. In Lift Trace, click **Copy height**. In OBS, click the **Height** box, press **Ctrl+A** and **Ctrl+V**, then click **OK**.

**What you should see:** **Lift Input** appears in OBS's Sources list. It may look like a black rectangle at first. Press a key to see an input note inside it. You will place this rectangle in the next step.

You do not need to remember or type the address's numbers. Use the width and height **currently shown in the app**.

For smoother motion, double-click **Lift Input** in OBS, enable **Use custom frame rate**, and enter **60 FPS** if that option is available. Then click **OK**.

## 5. Copy the numbers to place the overlay

The app's **Horizontal position (X)** is its left/right position; **Vertical position (Y)** is its up/down position. The app calculates them from **1P/2P and LIFT**, so you do not need to do the math.

1. In OBS's Sources list, drag **Lift Input** above the game capture. If its lock is closed, click it to unlock.
2. Right-click **Lift Input** → **Transform → Reset Transform**. This removes any previous stretching or cropping.
3. Right-click it again → **Transform → Edit Transform**. Set **Alignment** to **Top Left** and **Bounds Type** to **Automatic** (called **No bounds** in some versions). Leave size, rotation and crop unchanged.
4. In Lift Trace, click **Copy horizontal position**. In OBS, click the **X** box under **Position**, then press **Ctrl+A** and **Ctrl+V**.
5. In Lift Trace, click **Copy vertical position**. Paste into the **Y** box under **Position** in the same way, then close the window.
6. In OBS's preview, check that the rectangle's top edge meets the game's judgment line and the vertical key lanes match the game. When it fits, click the **lock beside Lift Input** in the Sources list.

**What you should see:** your input notes fall below the game's judgment line. For example, 1P, LIFT 401 and zero position adjustments give X **75**, Y **433** and height **290**. Use the copy buttons instead of memorizing these example numbers.

The 2P position is a starting estimate made by mirroring 1P. It has not yet been checked against an actual 2P game image, so check the placement on your screen.

If it is slightly off, open **Fine-tune the OBS position**. In **Move left / right**, enter **2** to move two pixels right or **-2** to move two pixels left. In **Move up / down**, enter **2** to move two pixels down or **-2** to move two pixels up. Pixels are units of distance on the screen. Copy the changed position and paste it into OBS again. Clicking **Match 1080p lane size** again resets both adjustments to 0.

If only the width differs, change **Total lane width**, then use **Copy width** to update the OBS Browser Source's **Width**. Changing width does not move the calculated starting position.

Do not stretch the rectangle by its corners or choose **Fit to Screen**. Changing its original size (100%) makes the lanes misalign; stretching vertically also changes the apparent falling speed. If changed accidentally, repeat the steps from **Reset Transform**. Once position is correct, adjust **Speed correction** if the falling speed differs, or **Display delay** if input notes appear too early.

## After changing height or play side

| What you changed | What to paste into OBS again |
| --- | --- |
| LIFT in the game | Enter the new LIFT in the app. Use **Copy vertical position** for Y in Edit Transform. If height is automatic, also use **Copy height** to update the Browser Source's height. |
| Display height only | Select **Height setting → Set manually**, enter a height, and use **Copy height** only. The Y position stays the same. |
| 1P ↔ 2P | Change the side in the app, then use **Copy horizontal position** for X in Edit Transform. |
| Left/right or up/down adjustment | Copy the position you changed and paste it into X or Y in Edit Transform. |

**The rectangle's size and position in OBS do not update themselves.** After changing the app, copy values into OBS as shown above. Changing only the display height does not change falling speed. Changing the game's LIFT, green number or SUDDEN+ values also affects the speed calculation.

## Next time, and when you finish

Next time, **double-click LiftTrace.exe → select your controller if needed → open OBS**. You do not have to repeat the key setup each time.

You may close the **browser tab containing the settings**. The input display continues.

Check the status message in the **small Lift Trace window**. If that window started the input display, **Quit** or closing the window also stops the display. Keep it open while using the overlay.

If the message says the display will continue after you close the window, OBS or another Lift Trace window was already running it. Closing this window leaves that original application running. To stop the input display too, close the OBS or Lift Trace window that started it.

## Optional: start it with OBS

First check that the steps above work. You can then have OBS start the input display without opening LiftTrace.exe separately.

1. Close the small Lift Trace window.
2. In OBS, choose **Tools → Scripts → +**.
3. Select **obs-lift-trace.lua** from the extracted LiftTrace folder.
4. Keep **Start automatically with OBS** enabled. Leave the other boxes unchanged to begin with.
5. Click **Start / connect input server**. On future starts, OBS also prepares the input display. If no controller is selected, choose it through **Open input settings**.

If OBS starts the input display, closing that OBS also stops the display. If Lift Trace was already running before OBS opened, closing OBS leaves it running. Detailed settings are in the [technical reference](REFERENCE.md#optional-obs-startup-settings).

## Update or remove

**To update:** click **Export settings** on your existing settings page and save the file. Close Lift Trace and OBS. Extract the new Windows ZIP into a **new folder**. Open the new LiftTrace.exe, click **Import**, and choose your saved settings file. Select the controller again and match OBS's width, height, X and Y to the values shown in the app. Keep the old folder until the new version works.

If you use automatic OBS startup, remove the old entry from OBS's Scripts list and add the file from the new folder.

**To remove:** export any settings you want to keep. Remove **Lift Input** and the optional Lift Trace script from OBS. Close Lift Trace and OBS, then delete the extracted folder.

## Troubleshooting

| What happens | Try this first |
| --- | --- |
| There is no LiftTrace.exe | Check that the download name contains **windows-x64**, then **Extract All**. |
| The small window opens, but no settings page | Click **Open settings** in the small window. |
| The app will not open or save | Extract again under **Documents** and run it without moving files out of that folder. |
| Windows or security software blocks it | This version is unsigned. Check that it came from this project's Releases and report the block message. Do not disable protection. |
| An error says something is already in use | Close another Lift Trace window you opened and retry. If it persists, report the exact message. |
| No controller appears | Check the connection, click **Scan**, and confirm the controller is in the mode you use for INFINITAS. |
| The keys or scratch look wrong | Repeat **Controller setup**, moving only the key or turntable the prompt asks for. |
| No input notes appear | Check whether **LIFT** is 0. Enter the game's LIFT value or choose a height with **Set manually**, then press a key. |
| OBS shows the settings page | Click **Copy address for OBS** again and paste into **Lift Input → URL** in OBS. |
| OBS cuts off part of the display | Use **Copy width** and **Copy height** to update the matching boxes in OBS. |
| OBS places it in the wrong spot | Check **1P/2P** and **LIFT**, then repeat section 5: **Reset Transform** and paste the horizontal/vertical positions. |
| Movement does not match the game | Check that the game's green/LIFT/SUDDEN+ values match the app. Adjust **Speed correction** and **Display delay** separately. |

If it still does not work, open **Issues** on GitHub and tell us **which button you reached** and **what appeared or what the error said**. Include the controller's product name for input problems. Leave unknown details blank. English, Korean and Japanese reports are welcome.

This app shows your key presses and scratch movements. It cannot identify game judgments or whether a hold is a real chart long note. Your controller and game-capture setup may need additional adjustment.

[Technical reference](REFERENCE.md) · [Validation status and checks](VALIDATION.md) · [Contributing](../CONTRIBUTING.md) · [Security and local data](../SECURITY.md)
