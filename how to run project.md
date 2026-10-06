# Tank Trouble Arena

## For players

Players do not install anything. Once the host shares the game URL, open it in a current web browser on a phone, tablet, or computer, then enter the room code if joining a private room. No app, account, or download is needed.

## For the host

The game server must be running at a publicly reachable URL before players can join. The host/deployer sets up the Python service; players only use their browser.

- **Project title:** Tank Trouble Arena
- **Project cover image:** [cover.svg](cover.svg)
- **Project description:** A browser-based tank arena with six selectable colors, public and four-digit private rooms, eleven combat maps including a jack-o'-lantern Halloween arena, four game modes, six themed three-lap race tracks with unique mechanics and music, eight race items, and a single-player AI opponent. Players join by opening the host URL; no account or player-side installation is required.
- **Project link / URL:** `http://localhost:8080` for local play. Replace with the deployed server URL when hosted publicly.

## Run the host

Install Python 3.10 or newer on the machine hosting the game, then from this folder run:

```sh
python -m pip install -r requirements.txt
python server.py
```

Open `http://localhost:8080` on the host. For phones or computers on the same Wi-Fi, open the game from the host computer using its network address (the lobby displays a **Same Wi-Fi** link and a Copy Link button when opened through the server), then share that address and the room code. Keep the server running and allow Python through Windows Firewall on Private networks if Windows prompts. Guests on a different Wi-Fi or mobile data need a publicly deployed URL; a local Wi-Fi address does not work over the internet. Private rooms use the four-digit code shown in the lobby.

## Game features

- Six tank colors: red, blue, green, purple, orange, and yellow.
- Eleven themed combat arenas with distinct scenery and cover obstacles, including a jack-o'-lantern Halloween map, plus six selectable race circuits: Operation Checkpoint, Neon Grid, Dust Devil Switchback, Polar Figure Eight, Canopy Run, and Haunted Hollow. Each race track has its own mechanic and generated background music; race backgrounds animate seasonal snow, leaves, petals, or fireflies.
- Battle, King of the Hill, Teams, and Racing Grand Prix mode selection. In King of the Hill, the AI prioritizes the hill circle; any living tank must hold it for 15 uninterrupted seconds; destroyed tanks respawn after one second, with capture progress resetting on leaving or being destroyed. The winner screen ranks everyone by hill control time, highlights the top three in gold, silver, and bronze, lists everyone else behind them, and plays an original victory fanfare. Race mode runs three laps with track checkpoints and boundaries.
- Race starts line tanks up on the start line. A hit causes the usual respawn but does not end the race; the AI keeps racing while opponents respawn. The race ends only when a racer completes lap three, then shows a gold, silver, and bronze podium followed by the remaining finish order.
- The finish screen embeds Rick Astley's official “Never Gonna Give You Up” music video as the victory theme. The browser may require pressing Play if it blocks autoplay.
- The race lobby previews its eight items: homing missile, turbo boost, shield, oil slick, EMP pulse, smoke screen, repair kit, and scatter shot. Rainbow question-mark item boxes spawn directly on the track and regenerate five seconds after collection. Trailing racers get stronger item odds; the AI follows the next item along the course and uses its pickups. Homing missiles target the racer ahead and show the target an incoming direction warning.
- The Shield surrounds its tank and absorbs one item hit. Homing missiles render as red checker-striped missiles in flight. The Halloween arena and Haunted Hollow use animated jack-o'-lantern item boxes instead of rainbow boxes.
- Item pickups play a sound; hits trigger an explosion animation and sound at the tank's last position.
- Tank cannon shots use the shooter's tank color, with a maximum of three live shots per player; cannon bullets ricochet from arena walls and obstacles. The AI tank and its cannon shots are white. Press E for a color-based special ability on a 10-second cooldown: fire, ice, grass vines, teleport, earth quake, or speed. The AI fires a homing, wall-bouncing mega missile that detonates after ten seconds, with a rocket launch sound. Orange Earth launches a large orange rock that homes toward a tank in front of the player and crushes it on impact. Item uses and each special ability have distinct synthesized sound effects; shields glow blue.
- Tank controls: WASD or arrow keys to move, turn, and Space to fire. Touch devices have on-screen controls.
- Choose **Single player vs AI** in Play style to add a pursuing computer opponent. Multiplayer rooms have no configured player cap; practical capacity depends on the host's CPU, memory, and network.
- The live scoreboard ranks every room participant, including AI. Scores persist through respawns; eliminations and completed race laps add points.
- Set the item drop interval from 5 to 60 seconds in Battle, Teams, or King of the Hill.

This project needs a reachable server to provide real multiplayer. It is not currently deployed to a public URL.

- Initial arena spawns and respawns choose clear positions away from walls and other tanks.
