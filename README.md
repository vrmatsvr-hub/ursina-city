# Ursina City - GTA-style sandbox in Python

Open-world crime & vehicle sandbox built with the Ursina engine: drift physics, KuKirin G2 and other
e-scooters with a tuning garage, Cobra 6 / Scream 100 fireworks, robberies, businesses, courier runs,
time trials and LAN / direct-IP multiplayer with public and private rooms.

**Windows:** download the repo (Code -> Download ZIP), unzip, double-click `START_GAME.bat`.
It installs Python + libraries if needed and auto-updates from this repository on every start.

## Install & run
    pip install ursina numpy
    python main.py

Python 3.10+ recommended. All models, shaders and sounds are generated on startup
(sounds are cached in ./generated_sounds the first time).

## Files
    main.py             game loop, input routing, pause menu
    world.py            city, shaders, day/night, streetlights, particles, audio synth, collision
    player.py           player movement, camera (V = first/third person), HUD + minimap
    vehicles.py         cars with drift physics, E-scooters / E-motorbikes with lean + EV drivetrain
    npcs.py             pedestrians, traffic AI, police chase, wanted level
    items_and_shops.py  fireworks (Cobra 6, Scream 100), robberies, businesses, tuning garage, courier, time trials
    menus.py            main menu, settings, multiplayer room browser
    network.py          multiplayer (socket + threading, LAN discovery, UPnP)
    updater.py          GitHub self-updater (reads version.json from this repo)
    version.json        current version + list of files the updater downloads

## Releasing an update
    1. edit the files, bump "version" in version.json (e.g. 1.0.0 -> 1.0.1)
    2. upload/commit them to this repo - every player gets the update on next start

## Controls
    WASD move/drive, SHIFT sprint/boost, SPACE jump/handbrake, mouse look
    E enter/steal/carjack/exit/interact, B buy snack, Q reopen tuning menu
    V camera, T day/night, LMB throw firework, TAB weapon wheel, 1/2/3 select
    H horn, R reset vehicle, F1 controls, ESC pause
    F9 one-time +5,000 coin bonus (remembered in savegame.json - delete that file to reset)

## Ways to earn money
    Rob Winkels: Nachtwinkel, Avondwinkel, Elektronica, Juwelier, Tankstation
    Businesses: E-Step Verhuur, Kapsalon Snackbar, Autowasstraat, Coffeeshop, Nachtclub (collect + upgrade)
    Courier runs: green beacon = pickup, yellow beacon = drop-off, beat the timer
    Time trials: drive into a blue beacon, hit every glowing ring (2 routes, record bonus)
    Drifting: long clean drifts build a combo meter (up to x5) and pay out when finished
