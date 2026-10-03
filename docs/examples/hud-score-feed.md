---
title: HUD score feed (preview)
parent: Examples
nav_order: 1
---

# HUD score feed (preview)

{: .note }
This is a **preview**, and the first *Naughty Bear* example here. There is no
`.srpatch` for it yet. A patch holds changed lines of script, and this edit is
to a Flash movie, which patches cannot carry today. It was made with prototype
scripts and a free Flash editor to prove the idea. Making it a normal part of
the app, with a patch you can apply, is planned for version 2.5.

Naughty Bear's score lines ("You smashed a window!", then "+500") use one line
of screen. A new line replaces the old one, and the rest wait in a queue and
appear one at a time. That makes the lines hard to read in the middle of a
fight, which is when you most want to know what just scored.

This example replaces it with a **stacked feed**: up to six lines at once,
newest on top, each with its score on the same line ("You hit a Fluffoul !!!
+ 200"), each fading out after about a second.

## Where the score lines come from

* The scripts decide *what* scores. Each event is defined in Lua with
  `AddScoreEventDefinition`, and its wording is a text string with the same
  hash. You can already change both with Seam Ripper.
* The scripts do not draw anything. The engine hands the HUD two strings, the
  text and the score, and then waits for the HUD to say it has finished
  showing them before it sends the next one.
* The HUD is a Flash movie (Scaleform, ActionScript 2) stored in
  `levelcommon.lu`. That is where the single line and the wait live.

So this is a HUD edit, not a script edit. The movie holds ActionScript, which is
not Lua.

## What was changed

1. The function the engine calls for each score line, `SetTextFearEvent`, no
   longer writes into the old single line. It joins the text and the score and
   passes them to a new clip.
2. A new **feed clip** was added to the movie, with six slots built from the
   game's own font and text style. Each slot is its own small clip, so it can
   fade on its own.
3. The feed clip's script (written for this example) keeps the six lines in
   fixed variables, shows them newest first, fades each one, and tells the
   engine it is done one frame after a line arrives, so the engine never waits.
4. A few functions that the game defines twice (the older copies are replaced
   by the later ones) were removed to make room, because the edited movie has
   to fit in the space of the original.

The feed clip's script is short and is not the game's code:

```actionscript
this.ROWS = 6;
this.HOLD = 1000;
this.FADE = 300;
this.LIFE = 1300;
this.texts = ["", "", "", "", "", ""];
this.times = [0, 0, 0, 0, 0, 0];
this.count = 0;
this.releasePending = false;
this.refresh = function()
{
   var now = getTimer();
   while(this.count > 0 && now - this.times[this.count - 1] >= this.LIFE)
   {
      this.count--;
   }
   var i = 0;
   while(i < this.ROWS)
   {
      var slot = this["s" + i];
      if(i < this.count)
      {
         var s = this.texts[i];
         if(typeof s != "string")
         {
            s = "";
         }
         var age = now - this.times[i];
         var al = 100;
         if(age > this.HOLD)
         {
            al = 100 * (1 - (age - this.HOLD) / this.FADE);
         }
         if(!(al > 0))
         {
            al = 0;
         }
         slot.t = s;
         slot._visible = true;
         slot._alpha = al;
      }
      else
      {
         slot.t = "";
         slot._visible = false;
      }
      i++;
   }
};
this.addLine = function(a, b)
{
   this.releasePending = true;
   var s = "";
   if(a != undefined)
   {
      s = String(a);
   }
   if(b != undefined && String(b) != "")
   {
      s = s + " " + String(b);
   }
   if(s == "")
   {
      return undefined;
   }
   var i = this.ROWS - 1;
   while(i > 0)
   {
      this.texts[i] = this.texts[i - 1];
      this.times[i] = this.times[i - 1];
      i--;
   }
   this.texts[0] = s;
   this.times[0] = getTimer();
   if(this.count < this.ROWS)
   {
      this.count++;
   }
   this.refresh();
};
this.onEnterFrame = function()
{
   if(this.releasePending)
   {
      this.releasePending = false;
      _root.CallEngineFunction("FearEventDisplayTextEnd");
   }
   this.refresh();
};
this.refresh();
stop();
```

One thing the first version got wrong is worth knowing if you write HUD
scripts. It kept the lines in an ActionScript array and used `splice` and
`length` to add and remove them. In this game's Flash engine that went wrong
after a while: broken entries appeared that could not be removed, and the feed
filled with the word "undefined". The version above uses no array methods at
all, only six fixed values that it shifts by hand, and it has not shown the
problem again.

## Change it

* `ROWS`: how many lines can show. The movie has six slots, so six is the
  most without adding more.
* `HOLD` and `FADE`: how long a line stays and how long it takes to fade.
* The size is the scale the feed clip is placed at (90%), set when the clip is
  added to the movie.

## What Seam Ripper does not do yet

Getting here took steps the app cannot do for you today:

* **Extract the movie** from the container. Seam Ripper already does this for
  Panic in Paradise (`pip_gfx`); the Naughty Bear movies need the same.
* **Edit the ActionScript.** This used a free Flash editor, JPEXS, which is a
  separate download and not part of Seam Ripper.
* **Put the movie back.** The chunk holds offsets that point past the movie,
  so the edited movie had to compress into exactly the size of the original.
  A proper import would move those offsets instead.

The plan for 2.5 is to add all three, so a HUD edit is made, shared and
applied like a script patch: a patch would hold only the changed
ActionScript, never the game's movie.

## Checked

* Played in Xenia on the retail Naughty Bear files: score lines appear and
  stack with the newest on top, each fades out after about a second, and
  several smashes in a row show several lines at once. Long lines still fit
  at 90% size. About four minutes through Level 1, with many bears seeing and
  hearing things at once, showed no stray "undefined" lines. The container
  passes Seam Ripper's integrity check and differs from retail only in the HUD
  movie.
* Not tested: the native PC port (restuff), multiplayer, other languages
  (long lines may be wider than the fields), and Panic in Paradise, whose HUD
  is a different movie.
