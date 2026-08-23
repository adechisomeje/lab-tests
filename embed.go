package labtests

import _ "embed"

// The dataset is embedded so a consuming binary has no runtime file or network
// dependency. Only the files the library actually reads are embedded; the
// by-clinic/ and by-department/ slices are derivable and would just bloat the
// binary.

//go:embed data/tests.json
var rawTests []byte

//go:embed data/clinic-profiles.json
var rawProfiles []byte

//go:embed data/categories.json
var rawCategories []byte

//go:embed data/providers.json
var rawProviders []byte
