#!/usr/bin/env node
/*
 * build_regmc_db.js
 *
 * Extract the COMPLETE data layer for a Showdown format.
 * One file, one source of truth, no heuristics downstream.
 *
 * Usage: node build_regmc_db.js [format] [outPath]
 */
const fs = require('fs');
const SHOWDOWN = '/home/morgrad/pokemon-showdown/dist';
const {Dex} = require(SHOWDOWN + '/sim/dex');

const FORMAT = process.argv[2] || 'gen9championsvgc2026regmc';
const OUT_PATH = process.argv[3] || '/home/morgrad/project/regmc_db.json';

const format = Dex.formats.get(FORMAT);
if (!format.exists) { console.error('Format not found:', FORMAT); process.exit(1); }
const d = Dex.forFormat(format);
console.log('Building DB for:', format.name, '| mod:', format.mod);

// ============ 1. SPECIES ============
const learnsets = d.data.Learnsets || {};

function legalMovesFor(sp) {
    let entry = learnsets[sp.id];
    if (!entry && sp.baseSpecies) {
        const baseId = sp.baseSpecies.toLowerCase().replace(/[^a-z0-9]/g, '');
        entry = learnsets[baseId];
    }
    if (!entry || !entry.learnset) return [];
    const out = [];
    for (const moveId of Object.keys(entry.learnset)) {
        const mv = d.moves.get(moveId);
        if (mv && mv.exists && !mv.isNonstandard) out.push(mv.name);
    }
    return out;
}

const species = {};
let speciesCount = 0;
for (const s of d.species.all()) {
    if (s.isNonstandard) continue;
    if (!s.name || !s.abilities) continue;

    const abils = [];
    for (const key of Object.keys(s.abilities)) {
        const aName = s.abilities[key];
        const a = d.abilities.get(aName);
        if (a && a.exists && !a.isNonstandard) abils.push(aName);
    }
    if (abils.length === 0) continue;

    species[s.name] = {
        name: s.name,
        id: s.id,
        baseSpecies: s.baseSpecies || s.name,
        forme: s.forme || null,
        types: Array.isArray(s.types) ? s.types : [s.types],
        baseStats: s.baseStats,
        abilities: abils,
        moves: legalMovesFor(s),
        tier: s.tier || null,
        isNonstandard: s.isNonstandard || null,
        megaStones: [],
    };
    speciesCount++;
}
console.log('Species:', speciesCount);

// ============ 2. ITEMS ============
const items = {};
let itemCount = 0;
for (const it of d.items.all()) {
    if (it.isNonstandard) continue;
    if (!it.name) continue;
    items[it.name] = {
        name: it.name,
        id: it.id,
        megaStone: it.megaStone || null,
        itemUser: it.itemUser || null,
        isBerry: !!it.isBerry,
        isChoice: !!it.isChoice,
        isGem: !!it.isGem,
        isPlate: !!it.isPlate,
        naturalGift: it.naturalGift
            ? { basePower: it.naturalGift.basePower, type: it.naturalGift.type }
            : null,
    };
    itemCount++;
}
console.log('Items:', itemCount);

// ============ 3. MOVES ============
const moves = {};
let moveCount = 0;
for (const mv of d.moves.all()) {
    if (mv.isNonstandard) continue;
    if (!mv.name) continue;
    moves[mv.name] = {
        name: mv.name,
        id: mv.id,
        type: mv.type,
        category: mv.category,
        basePower: mv.basePower,
        accuracy: mv.accuracy === true ? true : mv.accuracy,
        pp: mv.pp,
        priority: mv.priority,
        target: mv.target,
        flags: mv.flags || {},
    };
    moveCount++;
}
console.log('Moves:', moveCount);

// ============ 4. ABILITIES ============
const abilities = {};
let abilCount = 0;
for (const a of d.abilities.all()) {
    if (a.isNonstandard) continue;
    if (!a.name) continue;
    abilities[a.name] = {
        name: a.name,
        id: a.id,
        shortDesc: a.shortDesc || '',
    };
    abilCount++;
}
console.log('Abilities:', abilCount);

// ============ 5. NATURES ============
const natures = {};
for (const n of d.natures.all()) {
    if (!n.name) continue;
    natures[n.name] = {
        name: n.name,
        id: n.id,
        plus: n.plus || null,
        minus: n.minus || null,
    };
}
console.log('Natures:', Object.keys(natures).length);

// ============ 6. TYPES + CHART ============
const types = {};
for (const t of d.types.all()) {
    if (!t.name) continue;
    types[t.name] = { name: t.name, id: t.id };
}
let typeChart = {};
try {
    const tc = require(SHOWDOWN + '/data/typechart');
    // Showdown exports BattleTypeChart with keys like "Bug": {damageTaken: {...}}
    typeChart = tc.BattleTypeChart || tc.TypeChart || {};
} catch (e) {
    console.warn('Type chart load failed:', e.message);
}
console.log('Types:', Object.keys(types).length, '| chart entries:', Object.keys(typeChart).length);

// ============ 7. MEGA STONE MAPPING ============
const megaStones = {};
for (const [name, it] of Object.entries(items)) {
    if (!it.megaStone || typeof it.megaStone !== 'object') continue;
    for (const baseSpecies of Object.keys(it.megaStone)) {
        if (!megaStones[baseSpecies]) megaStones[baseSpecies] = [];
        megaStones[baseSpecies].push(name);
    }
}
console.log('Species with mega stones:', Object.keys(megaStones).length);

// Attach to species
for (const [name, sp] of Object.entries(species)) {
    if (sp.forme) {
        sp.megaStones = [];
    } else {
        sp.megaStones = megaStones[sp.name] || megaStones[sp.baseSpecies] || [];
    }
}

// ============ 8. RULES ============
const rules = {
    format: FORMAT,
    formatName: format.name,
    mod: format.mod,
    gameType: format.gameType || 'doubles',
    ruleset: format.ruleset || [],
    banlist: format.banlist || [],
    unbanlist: format.unbanlist || [],
    teamSize: 6,
    minTeamSize: 6,
    maxLevel: 50,
    evMaxPerStat: 32,
    evTotal: 66,
    itemClause: 1,
    speciesClause: true,
};

// ============ 9. WRITE ============
const out = {
    meta: {
        format: FORMAT,
        formatName: format.name,
        mod: format.mod,
        built: new Date().toISOString(),
        showdownPath: SHOWDOWN,
    },
    rules,
    natures,
    types,
    typeChart,
    items,
    moves,
    abilities,
    species,
};

fs.writeFileSync(OUT_PATH, JSON.stringify(out, null, 2));
const stat = fs.statSync(OUT_PATH);
console.log('\nWrote', OUT_PATH, `(${(stat.size / 1024).toFixed(1)} KB)`);
console.log('  species:', Object.keys(species).length);
console.log('  items:', Object.keys(items).length);
console.log('  moves:', Object.keys(moves).length);
console.log('  abilities:', Object.keys(abilities).length);
console.log('  natures:', Object.keys(natures).length);
console.log('  types:', Object.keys(types).length);
console.log('  typeChart:', Object.keys(typeChart).length)
